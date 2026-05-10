"""Shadow trading diagnostics for missed intraday opportunities."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .constants import (
    SHALLOW_PULLBACK_MIN_PCT,
    SHALLOW_PULLBACK_MAX_PCT,
)
from .events import TickEvent
from .strategy_types import StrategySignal

logger = logging.getLogger(__name__)


SHADOW_TAKE_PROFIT_1 = 0.010
SHADOW_TAKE_PROFIT_2 = 0.020
SHADOW_STOP_LOSS = -0.008
SHADOW_TRAIL_START = 0.010
SHADOW_TRAIL_GIVEBACK = 0.006
SHADOW_WINDOWS_SEC = (30, 60, 180, 300)
ESTIMATED_ROUND_TRIP_COST_PCT = 0.004


@dataclass
class ShadowCandidate:
    event_id: str
    event_type: str
    symbol: str
    name: str
    strategy: str
    reject_reason: str
    scan_time: datetime
    scan_price: float
    change_pct: float
    trading_value: float
    vol_ratio: float
    exec_strength: float
    leader_rank: int = 999
    leader_score: float = 0.0
    entry_reference_price: float = 0.0
    expected_entry_price: float = 0.0
    ask1_entry_price: float = 0.0
    bid1_exit_price: float = 0.0
    spread_at_entry: float = 0.0
    estimated_slippage: float = 0.0
    time_bucket: str = ""
    high: float = 0.0
    low: float = 0.0
    high_at: datetime | None = None
    low_at: datetime | None = None
    windows_done: set[int] = field(default_factory=set)
    recorded_final: bool = False


@dataclass
class ShadowPosition:
    strategy: str
    symbol: str
    entry_time: datetime
    entry_price: float
    entry_reason: str
    leader_rank: int = 999
    leader_score: float = 0.0
    high: float = 0.0
    low: float = 0.0
    exited: bool = False


class ShadowTradingEngine:
    """Tracks counterfactual entries without placing orders.

    The engine answers two operational questions:
    - did a scanned candidate move enough after scan to justify looser entries?
    - which relaxed entry family would have caught the move before risk limits?
    """

    def __init__(self, base_dir: str | Path = "data/shadow_trading") -> None:
        self._base_dir = Path(base_dir)
        self._candidates: dict[str, ShadowCandidate] = {}
        self._candidate_events: dict[str, ShadowCandidate] = {}
        self._positions: dict[tuple[str, str], ShadowPosition] = {}

    def observe_candidates(self, candidates: list[Any]) -> None:
        now = datetime.now()
        for c in candidates:
            price = float(getattr(c, "price", 0.0) or 0.0)
            if price <= 0:
                continue
            symbol = str(getattr(c, "symbol", ""))
            if not symbol:
                continue
            existing = self._candidates.get(symbol)
            if existing and (now - existing.scan_time).total_seconds() < 60:
                self._refresh_candidate(existing, c)
                self._update_candidate_extremes(existing, price, now)
                self._record_candidate_windows(existing, now)
                continue
            event_id = self._event_id(symbol, "candidate", "scan", now, bucket_seconds=60)
            candidate = ShadowCandidate(
                event_id=event_id,
                event_type="candidate",
                symbol=symbol,
                name=str(getattr(c, "name", "") or ""),
                strategy="scan",
                reject_reason="",
                scan_time=now,
                scan_price=price,
                change_pct=float(getattr(c, "change_pct", 0.0) or 0.0),
                trading_value=float(getattr(c, "trading_value", 0.0) or 0.0),
                vol_ratio=float(getattr(c, "vol_ratio", 0.0) or 0.0),
                exec_strength=float(getattr(c, "exec_strength", 0.0) or 0.0),
                leader_rank=int(getattr(c, "leader_rank", 999) or 999),
                leader_score=float(getattr(c, "leader_score", 0.0) or 0.0),
                entry_reference_price=price,
                expected_entry_price=price,
                ask1_entry_price=float(getattr(c, "ask1_price", 0.0) or price),
                bid1_exit_price=float(getattr(c, "bid1_price", 0.0) or price),
                spread_at_entry=self._spread_pct(
                    float(getattr(c, "bid1_price", 0.0) or 0.0),
                    float(getattr(c, "ask1_price", 0.0) or 0.0),
                    price,
                ),
                estimated_slippage=0.001,
                time_bucket=self._time_bucket(now, 60),
                high=price,
                low=price,
                high_at=now,
                low_at=now,
            )
            self._candidates[symbol] = candidate
            self._candidate_events[event_id] = candidate
            self._open_position("shadow_scan_immediate", candidate, price, "scan_immediate")
            if candidate.leader_rank <= 2:
                self._open_position("shadow_leader_only", candidate, price, "leader_rank")
            if candidate.leader_score >= 70:
                self._open_position("shadow_score_70", candidate, price, "leader_score_70")
            self._append_event("candidate_scan", self._candidate_payload(candidate))
        self.flush_windows()

    def observe_rejected_candidate(
        self,
        candidate_source: Any,
        *,
        strategy: str,
        reject_reason: str,
        metrics: dict | None = None,
        bucket_seconds: int = 60,
    ) -> None:
        """Track rejected candidates so later MFE/MAE can prove missed edge vs avoided loss."""
        now = datetime.now()
        symbol = str(getattr(candidate_source, "symbol", "") or "")
        price = float(
            (metrics or {}).get("expected_entry_price")
            or getattr(candidate_source, "price", 0.0)
            or 0.0
        )
        if not symbol or price <= 0:
            return
        event_id = self._event_id(symbol, "rejected", strategy, now, bucket_seconds=bucket_seconds)
        existing = self._candidate_events.get(event_id)
        if existing:
            self._refresh_candidate(existing, candidate_source)
            existing.reject_reason = reject_reason or existing.reject_reason
            self._record_candidate_windows(existing, now)
            return

        metrics = metrics or {}
        bid1 = float(metrics.get("bid1") or metrics.get("bid1_price") or 0.0)
        ask1 = float(metrics.get("ask1") or metrics.get("ask1_price") or 0.0)
        rejected = ShadowCandidate(
            event_id=event_id,
            event_type="rejected_candidate",
            symbol=symbol,
            name=str(getattr(candidate_source, "name", "") or metrics.get("name") or ""),
            strategy=strategy,
            reject_reason=reject_reason,
            scan_time=now,
            scan_price=price,
            change_pct=float(getattr(candidate_source, "change_pct", metrics.get("change_pct", 0.0)) or 0.0),
            trading_value=float(getattr(candidate_source, "trading_value", metrics.get("trading_value", 0.0)) or 0.0),
            vol_ratio=float(getattr(candidate_source, "vol_ratio", metrics.get("vol_ratio", 0.0)) or 0.0),
            exec_strength=float(getattr(candidate_source, "exec_strength", metrics.get("exec_strength", 0.0)) or 0.0),
            leader_rank=int(getattr(candidate_source, "leader_rank", metrics.get("leader_rank", 999)) or 999),
            leader_score=float(getattr(candidate_source, "leader_score", metrics.get("leader_score", 0.0)) or 0.0),
            entry_reference_price=price,
            expected_entry_price=float(metrics.get("expected_entry_price") or price),
            ask1_entry_price=ask1 or price,
            bid1_exit_price=bid1 or price,
            spread_at_entry=self._spread_pct(bid1, ask1, price),
            estimated_slippage=float(metrics.get("estimated_slippage") or 0.001),
            time_bucket=self._time_bucket(now, bucket_seconds),
            high=price,
            low=price,
            high_at=now,
            low_at=now,
        )
        self._candidate_events[event_id] = rejected
        self._append_event("rejected_candidate_scan", self._candidate_payload(rejected))

    def on_tick(self, tick: TickEvent, signal_snapshot: dict | None = None) -> None:
        if tick.price <= 0:
            return
        now = tick.ts if isinstance(tick.ts, datetime) else datetime.now()
        symbol_events = [c for c in self._candidate_events.values() if c.symbol == tick.symbol]
        if not symbol_events:
            return
        candidate = self._candidates.get(tick.symbol)
        for tracked in symbol_events:
            self._update_candidate_extremes(tracked, tick.price, now)
            self._record_candidate_windows(tracked, now)
        if candidate:
            self._maybe_open_pending_strategies(candidate, tick, signal_snapshot or {})
        self._update_positions(tick)

    def mark_real_signal(self, symbol: str, strategy: str = "current_strategy") -> None:
        candidate = self._candidates.get(symbol)
        if candidate and candidate.scan_price > 0:
            self._open_position(strategy, candidate, candidate.scan_price, "real_signal_seen")

    def observe_strategy_signal(self, signal: StrategySignal) -> None:
        """Record strategy-router signals in the same shadow ledger."""
        candidate = self._candidates.get(signal.symbol)
        if not candidate or not signal.entry_price:
            return
        if signal.shadow_only or not signal.live_allowed:
            self._open_position(
                f"shadow_{signal.strategy_name}",
                candidate,
                float(signal.entry_price),
                signal.reason,
            )

    def summary(self) -> dict[str, Any]:
        open_positions = [p for p in self._positions.values() if not p.exited]
        return {
            "tracked_candidates": len(self._candidates),
            "open_shadow_positions": len(open_positions),
            "strategies": sorted({p.strategy for p in self._positions.values()}),
        }

    def flush_windows(self, now: datetime | None = None) -> None:
        """Close elapsed MFE/MAE windows even when no fresh tick arrives."""
        now = now or datetime.now()
        for candidate in list(self._candidate_events.values()):
            self._record_candidate_windows(candidate, now)

    def _refresh_candidate(self, candidate: ShadowCandidate, source: Any) -> None:
        candidate.change_pct = float(getattr(source, "change_pct", candidate.change_pct) or 0.0)
        candidate.trading_value = float(getattr(source, "trading_value", candidate.trading_value) or 0.0)
        candidate.vol_ratio = float(getattr(source, "vol_ratio", candidate.vol_ratio) or 0.0)
        candidate.exec_strength = float(getattr(source, "exec_strength", candidate.exec_strength) or 0.0)
        candidate.leader_rank = int(getattr(source, "leader_rank", candidate.leader_rank) or 999)
        candidate.leader_score = float(getattr(source, "leader_score", candidate.leader_score) or 0.0)

    def _maybe_open_pending_strategies(
        self,
        candidate: ShadowCandidate,
        tick: TickEvent,
        signal_snapshot: dict,
    ) -> None:
        drawdown = tick.price / candidate.high - 1.0 if candidate.high > 0 else 0.0
        pullback = abs(min(0.0, drawdown))
        vwap_gap = float(signal_snapshot.get("vwap_gap", 0.0) or 0.0)
        exec_strength = float(signal_snapshot.get("exec_strength", 0.0) or 0.0)

        if (
            candidate.leader_rank <= 2
            and SHALLOW_PULLBACK_MIN_PCT <= pullback <= SHALLOW_PULLBACK_MAX_PCT
            and exec_strength >= 110.0
        ):
            self._open_position(
                "shadow_shallow_pullback",
                candidate,
                tick.price,
                f"pullback={pullback:.4f}",
            )
        if 0.005 <= pullback <= 0.015 and exec_strength >= 115.0:
            self._open_position(
                "shadow_breakout_relaxed",
                candidate,
                tick.price,
                f"relaxed_pullback={pullback:.4f}",
            )
        if vwap_gap >= 0.0 and exec_strength >= 110.0:
            self._open_position(
                "shadow_vwap_reclaim",
                candidate,
                tick.price,
                f"vwap_gap={vwap_gap:.4f}",
            )

    def _open_position(
        self,
        strategy: str,
        candidate: ShadowCandidate,
        price: float,
        reason: str,
    ) -> None:
        key = (strategy, candidate.symbol)
        if key in self._positions:
            return
        pos = ShadowPosition(
            strategy=strategy,
            symbol=candidate.symbol,
            entry_time=datetime.now(),
            entry_price=price,
            entry_reason=reason,
            leader_rank=candidate.leader_rank,
            leader_score=candidate.leader_score,
            high=price,
            low=price,
        )
        self._positions[key] = pos
        self._append_event("shadow_entry", self._position_payload(pos, candidate))

    def _update_positions(self, tick: TickEvent) -> None:
        now = tick.ts if isinstance(tick.ts, datetime) else datetime.now()
        for pos in list(self._positions.values()):
            if pos.exited or pos.symbol != tick.symbol:
                continue
            pos.high = max(pos.high, tick.price)
            pos.low = min(pos.low, tick.price)
            pnl = tick.price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
            mfe = pos.high / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
            exit_reason = ""
            if pnl <= SHADOW_STOP_LOSS:
                exit_reason = "stop_loss"
            elif pnl >= SHADOW_TAKE_PROFIT_2:
                exit_reason = "take_profit_2"
            elif pnl >= SHADOW_TAKE_PROFIT_1:
                exit_reason = "take_profit_1"
            elif mfe >= SHADOW_TRAIL_START and pnl <= mfe - SHADOW_TRAIL_GIVEBACK:
                exit_reason = "trailing_stop"
            if exit_reason:
                pos.exited = True
                payload = self._position_payload(pos, self._candidates.get(pos.symbol))
                payload.update({
                    "exit_time": now.isoformat(),
                    "exit_price": tick.price,
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl, 5),
                    "mfe_pct": round(mfe, 5),
                    "mae_pct": round(pos.low / pos.entry_price - 1.0, 5),
                    "estimated_round_trip_cost_pct": round(0.004, 5),
                    "net_pnl_after_cost_pct": round(pnl - 0.004, 5),
                })
                self._append_event("shadow_exit", payload)
                self._append_event("shadow_trade_result", payload)

    def _record_candidate_windows(self, candidate: ShadowCandidate, now: datetime) -> None:
        elapsed = (now - candidate.scan_time).total_seconds()
        for window in SHADOW_WINDOWS_SEC:
            if window in candidate.windows_done or elapsed < window:
                continue
            candidate.windows_done.add(window)
            entry = candidate.ask1_entry_price or candidate.expected_entry_price or candidate.scan_price
            exit_high = candidate.high * (1.0 - candidate.spread_at_entry / 2.0)
            exit_low = candidate.low * (1.0 - candidate.spread_at_entry / 2.0)
            candidate.bid1_exit_price = exit_high
            mfe = exit_high / entry - 1.0 if entry > 0 else 0.0
            mae = exit_low / entry - 1.0 if entry > 0 else 0.0
            net_mfe = mfe - ESTIMATED_ROUND_TRIP_COST_PCT - candidate.estimated_slippage
            net_expectancy = net_mfe
            label = "30s" if window == 30 else f"{window // 60}m"
            payload = self._candidate_payload(candidate)
            payload.update({
                "window_sec": window,
                "window_label": label,
                "entry_reference_price": candidate.entry_reference_price,
                "expected_entry_price": candidate.expected_entry_price,
                "ask1_entry_price": candidate.ask1_entry_price,
                "bid1_exit_price": candidate.bid1_exit_price,
                "high_after_entry": candidate.high,
                "low_after_entry": candidate.low,
                "mfe_pct": round(mfe, 5),
                "mae_pct": round(mae, 5),
                "net_mfe_pct": round(net_mfe, 5),
                "net_expectancy": round(net_expectancy, 5),
                "spread_at_entry": round(candidate.spread_at_entry, 5),
                "estimated_slippage": round(candidate.estimated_slippage, 5),
                "max_favorable_time": candidate.high_at.isoformat() if candidate.high_at else None,
                "max_adverse_time": candidate.low_at.isoformat() if candidate.low_at else None,
                "missed_opportunity": mfe >= SHADOW_TAKE_PROFIT_1,
                "avoided_loss": mae <= SHADOW_STOP_LOSS,
            })
            prefix = "rejected_candidate" if candidate.event_type == "rejected_candidate" else "candidate"
            self._append_event(f"{prefix}_window_{label}", payload)
            self._append_event(f"{prefix}_window", payload)
            logger.info(
                "[ShadowMFE] symbol=%s name=%s window=%ds mfe=%.2f%% mae=%.2f%% "
                "missed=%s avoided_loss=%s leader_rank=%s leader_score=%.1f",
                candidate.symbol, candidate.name, window, mfe * 100, mae * 100,
                str(mfe >= SHADOW_TAKE_PROFIT_1).lower(),
                str(mae <= SHADOW_STOP_LOSS).lower(),
                candidate.leader_rank, candidate.leader_score,
            )

    def _update_candidate_extremes(self, candidate: ShadowCandidate, price: float, now: datetime) -> None:
        if price > candidate.high:
            candidate.high = price
            candidate.high_at = now
        if price < candidate.low:
            candidate.low = price
            candidate.low_at = now

    def _candidate_payload(self, candidate: ShadowCandidate) -> dict[str, Any]:
        payload = asdict(candidate)
        payload.pop("windows_done", None)
        payload["scan_time"] = candidate.scan_time.isoformat()
        payload["high_at"] = candidate.high_at.isoformat() if candidate.high_at else None
        payload["low_at"] = candidate.low_at.isoformat() if candidate.low_at else None
        return payload

    @staticmethod
    def _time_bucket(now: datetime, bucket_seconds: int) -> str:
        epoch = int(now.timestamp())
        bucket = epoch - (epoch % bucket_seconds)
        return datetime.fromtimestamp(bucket).isoformat(timespec="seconds")

    @classmethod
    def _event_id(
        cls,
        symbol: str,
        event_type: str,
        strategy: str,
        now: datetime,
        *,
        bucket_seconds: int,
    ) -> str:
        return f"{symbol}:{event_type}:{strategy}:{cls._time_bucket(now, bucket_seconds)}"

    @staticmethod
    def _spread_pct(bid1: float, ask1: float, price: float) -> float:
        if bid1 > 0 and ask1 > 0 and price > 0 and ask1 >= bid1:
            return (ask1 - bid1) / price
        return 0.0

    def _position_payload(
        self,
        pos: ShadowPosition,
        candidate: ShadowCandidate | None,
    ) -> dict[str, Any]:
        payload = asdict(pos)
        payload["entry_time"] = pos.entry_time.isoformat()
        if candidate:
            payload.update({
                "name": candidate.name,
                "scan_time": candidate.scan_time.isoformat(),
                "scan_price": candidate.scan_price,
                "change_pct": candidate.change_pct,
                "trading_value": candidate.trading_value,
                "vol_ratio": candidate.vol_ratio,
                "exec_strength": candidate.exec_strength,
            })
        return payload

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["event_type"] = event_type
        payload["recorded_at"] = datetime.now().isoformat()
        path = self._base_dir / f"{date.today().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
