"""CloseBetScanner — 종가베팅 후보 필터링."""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .constants import (
    CLOSE_BET_MAX_CHANGE_PCT,
    CLOSE_BET_MAX_VI_COUNT_60M,
    CLOSE_BET_MIN_CHANGE_PCT,
    CLOSE_BET_MIN_EXEC_STRENGTH_30M,
    CLOSE_BET_MIN_KOSDAQ_CHANGE_PCT,
    CLOSE_BET_MIN_TRADING_VALUE,
    MIN_EXEC_SAMPLES_30M,
    SCAN_TOP_N,
)
from .position_type import PositionType
from .nxt_market import build_nxt_context, close_bet_nxt_score_adjustment
from .venue import MarketSession

logger = logging.getLogger(__name__)


@dataclass
class CloseBetCandidate:
    symbol: str
    name: str | None
    price: float
    change_pct: float
    exec_strength_30m: float
    vi_count_60m: int
    trading_value: float
    kosdaq_change_pct: float
    score: float | None = None
    market: str = "KOSDAQ"
    reason: str | None = None
    checked_at: datetime | None = None
    strategy_id: str = "close_bet_krx_only"
    eligible_live: bool = True
    near_miss: bool = False
    reject_reason: str | None = None
    nxt_score_adjustment: float = 0.0
    nxt_metadata: dict | None = None
    close_bet_grade: str = "b_keep_candidate"
    position_size_multiplier: float = 1.0
    morning_exit_priority: float = 40.0
    hold_extension_allowed: bool = False


class CloseBetScanner:
    """14:50~15:15 종가베팅 후보를 기존 스캘핑 후보와 분리해 선별한다."""

    def __init__(
        self,
        adapter: Any,
        signal_engine: Any,
        position_mgr: Any,
        *,
        env: str = "demo",
        market_scanner: Any = None,
        top_n: int = SCAN_TOP_N,
    ) -> None:
        self._adapter = adapter
        self._signal_engine = signal_engine
        self._position_mgr = position_mgr
        self._env = env
        self._market_scanner = market_scanner
        self._top_n = top_n
        self.last_diagnostics: dict[str, Any] = {}
        self.last_reject_samples: list[dict[str, Any]] = []

    def scan(self) -> list[CloseBetCandidate]:
        kosdaq_change_pct = self._kosdaq_change_pct()
        if kosdaq_change_pct <= CLOSE_BET_MIN_KOSDAQ_CHANGE_PCT:
            logger.info(
                "CLOSE_BET_SCAN blocked: kosdaq=%.3f%%",
                kosdaq_change_pct * 100,
            )
            return []

        intraday_symbols = self._intraday_open_symbols()
        raw_items = self._volume_ranking_items()
        candidates: list[CloseBetCandidate] = []
        fail_counts = {
            "fail_change_pct": 0,
            "fail_exec_strength_30m": 0,
            "fail_vi_count_60m": 0,
            "fail_trading_value": 0,
            "fail_intraday_position": 0,
            "fail_excluded_security": 0,
            "fail_insufficient_samples": 0,
            "fail_overnight_risk": 0,
            "near_miss": 0,
        }
        reject_samples: list[dict[str, Any]] = []

        for item in raw_items:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            exec_strength_30m = self.exec_strength_30m_avg(symbol)
            candidate = CloseBetCandidate(
                symbol=symbol,
                name=item.get("name") or None,
                price=float(item.get("price") or 0),
                change_pct=float(item.get("change_rate") or item.get("change_pct") or 0),
                exec_strength_30m=exec_strength_30m,
                vi_count_60m=int(item.get("vi_count_60m") or 0),
                trading_value=float(item.get("trading_value") or 0),
                kosdaq_change_pct=kosdaq_change_pct,
                market=item.get("market") or "KOSDAQ",
                checked_at=datetime.now(),
            )
            if symbol in intraday_symbols:
                candidate.reason = "intraday_position_exists"
                candidate.reject_reason = "intraday_position_exists"
                fail_counts["fail_intraday_position"] += 1
                continue
            reject_reason = self._reject_reason(candidate, item)
            if reject_reason:
                candidate.reject_reason = reject_reason
                if reject_reason == "exec_strength_30m_below_threshold" and candidate.exec_strength_30m >= 100:
                    candidate.near_miss = True
                    candidate.eligible_live = False
                    candidate.reason = "near_miss"
                    candidate.score = self._score(candidate)
                    fail_counts["near_miss"] += 1
                    self._log_near_miss(candidate)
                self._increment_fail(fail_counts, reject_reason)
                if len(reject_samples) < 10:
                    reject_samples.append(self._reject_log_payload(candidate, reject_reason))
                continue
            nxt_ctx = build_nxt_context(
                self._adapter,
                symbol,
                session=MarketSession.NXT_AFTER,
                env=self._env,
                krx_reference_price=candidate.price,
                krx_turnover=candidate.trading_value,
            )
            nxt_adj, nxt_meta = close_bet_nxt_score_adjustment(nxt_ctx)
            candidate.nxt_score_adjustment = nxt_adj
            candidate.nxt_metadata = nxt_meta
            candidate.strategy_id = "close_bet_nxt_aware" if not nxt_meta.get("nxt_data_missing") else "close_bet_krx_only"
            candidate.score = self._score(candidate) + nxt_adj
            candidate.close_bet_grade = str(nxt_meta.get("close_bet_grade") or "b_keep_candidate")
            candidate.position_size_multiplier = float(nxt_meta.get("position_size_multiplier") or 1.0)
            candidate.morning_exit_priority = float(nxt_meta.get("morning_exit_priority") or 40.0)
            candidate.hold_extension_allowed = bool(nxt_meta.get("hold_extension_allowed") or False)
            if nxt_meta.get("overnight_action") == "block_entry":
                candidate.eligible_live = False
                candidate.reject_reason = "overnight_entry_blocked"
                candidate.reason = nxt_meta.get("overnight_reason") or "overnight_entry_blocked"
                fail_counts["fail_overnight_risk"] += 1
                if len(reject_samples) < 10:
                    reject_samples.append(self._reject_log_payload(candidate, "overnight_entry_blocked"))
                logger.info(
                    "[CLOSE_BET_REJECT_OVERNIGHT] symbol=%s risk=%.1f reason=%s exhaustion=%.1f liquidity_trust=%.1f",
                    symbol,
                    float(nxt_meta.get("overnight_entry_risk") or 0),
                    candidate.reason,
                    float(nxt_meta.get("exhaustion_score") or 0),
                    float(nxt_meta.get("liquidity_trust") or 0),
                )
                continue
            if nxt_meta.get("overnight_action") == "enter_reduced":
                candidate.strategy_id = "close_bet_nxt_exit_priority"
            elif candidate.hold_extension_allowed:
                candidate.strategy_id = "close_bet_nxt_hold_extension"
            candidate.reason = "close_bet_candidate"
            candidates.append(candidate)

        top_reason = self._top_reject_reason(fail_counts)
        self.last_diagnostics = {
            "raw": len(raw_items),
            "passed": len(candidates),
            "top_reject_reason": top_reason,
            **fail_counts,
        }
        self.last_reject_samples = list(reject_samples)
        logger.info(
            "CLOSE_BET_SCAN raw=%d passed=%d fail_change_pct=%d fail_exec_strength_30m=%d "
            "fail_vi_count_60m=%d fail_trading_value=%d fail_intraday_position=%d "
            "fail_overnight_risk=%d "
            "fail_excluded_security=%d fail_insufficient_samples=%d near_miss=%d top_reject_reason=%s kosdaq=%.3f%%",
            len(raw_items), len(candidates), fail_counts["fail_change_pct"],
            fail_counts["fail_exec_strength_30m"], fail_counts["fail_vi_count_60m"],
            fail_counts["fail_trading_value"], fail_counts["fail_intraday_position"],
            fail_counts["fail_overnight_risk"],
            fail_counts["fail_excluded_security"], fail_counts["fail_insufficient_samples"],
            fail_counts["near_miss"], top_reason, kosdaq_change_pct * 100,
        )
        if not candidates:
            logger.info(
                "[CLOSE_BET_NO_CANDIDATE] reason=SCAN_EXECUTED_NO_MATCH raw=%d top_reject_reason=%s",
                len(raw_items), top_reason,
            )
        for payload in reject_samples:
            logger.info("[CLOSE_BET_REJECT] %s", " ".join(f"{k}={v}" for k, v in payload.items()))
        return candidates

    def exec_strength_30m_avg(self, symbol: str) -> float:
        getter = getattr(self._signal_engine, "get_exec_strength_samples", None)
        samples = getter(symbol, lookback_minutes=30) if getter else []
        if len(samples) < MIN_EXEC_SAMPLES_30M:
            logger.info(
                "CLOSE_BET_SCAN %s exec_strength_30m insufficient samples=%d",
                symbol, len(samples),
            )
            return 0.0

        values = sorted(float(v) for v in samples)
        if len(values) >= 5:
            lo = values[int(len(values) * 0.05)]
            hi = values[min(len(values) - 1, int(len(values) * 0.95))]
            values = [min(max(v, lo), hi) for v in values]
        avg = statistics.fmean(values)
        logger.info(
            "CLOSE_BET_SCAN %s exec_strength_30m=%.1f samples=%d",
            symbol, avg, len(samples),
        )
        return avg

    def _passes(self, c: CloseBetCandidate, raw: dict) -> bool:
        return self._reject_reason(c, raw) is None

    def _reject_reason(self, c: CloseBetCandidate, raw: dict) -> str | None:
        if c.change_pct < CLOSE_BET_MIN_CHANGE_PCT:
            return "change_pct_below_threshold"
        if c.change_pct >= CLOSE_BET_MAX_CHANGE_PCT:
            return "change_pct_above_max"
        if c.exec_strength_30m <= 0:
            return "insufficient_exec_samples"
        if c.exec_strength_30m < CLOSE_BET_MIN_EXEC_STRENGTH_30M:
            return "exec_strength_30m_below_threshold"
        if c.vi_count_60m > CLOSE_BET_MAX_VI_COUNT_60M:
            return "vi_count_60m_above_threshold"
        if c.trading_value < CLOSE_BET_MIN_TRADING_VALUE:
            return "trading_value_below_threshold"
        if c.kosdaq_change_pct <= CLOSE_BET_MIN_KOSDAQ_CHANGE_PCT:
            return "kosdaq_below_threshold"
        unsafe_flags = (
            "is_managed",
            "is_warning",
            "is_investment_caution",
            "is_investment_warning",
            "is_investment_danger",
            "is_short_term_overheated",
            "is_trading_halted",
            "is_delisting_trade",
            "is_etf",
            "is_etn",
            "is_spac",
            "is_vi",
        )
        if any(bool(raw.get(flag)) for flag in unsafe_flags):
            return "excluded_security"
        if self._is_preferred_share(c.symbol):
            return "excluded_security"
        return None

    def _score(self, c: CloseBetCandidate) -> float:
        return round(
            c.change_pct * 1000
            + (c.exec_strength_30m - CLOSE_BET_MIN_EXEC_STRENGTH_30M)
            + min(c.trading_value / 100e9, 5.0) * 5,
            2,
        )

    @staticmethod
    def _increment_fail(counts: dict[str, int], reason: str) -> None:
        mapping = {
            "change_pct_below_threshold": "fail_change_pct",
            "change_pct_above_max": "fail_change_pct",
            "exec_strength_30m_below_threshold": "fail_exec_strength_30m",
            "insufficient_exec_samples": "fail_insufficient_samples",
            "vi_count_60m_above_threshold": "fail_vi_count_60m",
            "trading_value_below_threshold": "fail_trading_value",
            "excluded_security": "fail_excluded_security",
        }
        key = mapping.get(reason)
        if key:
            counts[key] += 1

    @staticmethod
    def _top_reject_reason(counts: dict[str, int]) -> str:
        non_zero = {k: v for k, v in counts.items() if v > 0 and k != "near_miss"}
        if not non_zero:
            return "-"
        return max(non_zero.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _reject_log_payload(c: CloseBetCandidate, reason: str) -> dict[str, Any]:
        return {
            "symbol": c.symbol,
            "name": c.name or "-",
            "change_pct": round(c.change_pct, 4),
            "exec_strength_30m": round(c.exec_strength_30m, 1),
            "exec_threshold": CLOSE_BET_MIN_EXEC_STRENGTH_30M,
            "vi_count_60m": c.vi_count_60m,
            "trading_value": round(c.trading_value, 0),
            "reason": reason,
        }

    @staticmethod
    def _log_near_miss(c: CloseBetCandidate) -> None:
        logger.info(
            "[CLOSE_BET_NEAR_MISS] symbol=%s exec_strength_30m=%.1f threshold=%.1f eligible_live=false reject_reason=%s",
            c.symbol, c.exec_strength_30m, CLOSE_BET_MIN_EXEC_STRENGTH_30M,
            c.reject_reason or "exec_strength_30m_below_threshold",
        )

    def _volume_ranking_items(self) -> list[dict]:
        try:
            result = self._adapter.get_volume_ranking(top_n=self._top_n, env_dv=self._env)
            return list(result.get("items") or [])
        except Exception as exc:
            logger.warning("CLOSE_BET_SCAN volume ranking failed: %s", exc)
            return []

    def _kosdaq_change_pct(self) -> float:
        if self._market_scanner is not None:
            return float(getattr(self._market_scanner, "kosdaq_change_pct", 0.0))
        try:
            result = self._adapter.get_quote("U001", market_code="U", env_dv=self._env)
            if result.get("status") == "ok":
                return float((result.get("quote") or {}).get("change_rate") or 0) / 100.0
        except Exception:
            pass
        return 0.0

    def _intraday_open_symbols(self) -> set[str]:
        if not self._position_mgr:
            return set()
        return {
            symbol
            for symbol, pos in self._position_mgr.active_positions().items()
            if getattr(pos, "position_type", PositionType.UNKNOWN)
            != PositionType.CLOSE_BET
        }

    @staticmethod
    def _is_preferred_share(symbol: str) -> bool:
        return len(symbol) == 6 and symbol[-1] != "0"
