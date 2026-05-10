"""RiskManager — 일 손실 한도, 연속 손절, 시간 기반 쿨다운 게이트키퍼."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .constants import (
    DAILY_LOSS_LIMIT_PCT, MAX_CONSECUTIVE_LOSSES,
    MAX_SYMBOLS, MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE_PCT,
    KOSDAQ_HALT_THRESHOLD, CLOSE_BET_MIN_KOSDAQ_CHANGE_PCT,
    OVERNIGHT_MAX_PER_SYMBOL, OVERNIGHT_MAX_TOTAL,
    MAX_DAILY_TRADES, MAX_TRADES_PER_SYMBOL,
    MIN_ENTRY_SCORE, ADAPTIVE_SCORE_LOSS_1, ADAPTIVE_SCORE_LOSS_2,
    MAX_EXPOSURE_OPENING_MOMENTUM, MAX_EXPOSURE_SHALLOW_PULLBACK,
    MAX_EXPOSURE_VWAP_RECLAIM, MAX_EXPOSURE_DEEP_PULLBACK,
    MAX_LOSS_PER_SYMBOL_PCT, MAX_TRADES_PER_STRATEGY, REENTRY_COOLDOWN_SECS,
)
from .position_type import PositionType

logger = logging.getLogger(__name__)

# ── 쿨다운 상수 ───────────────────────────────────────────────────────────────
COOLDOWN_AFTER_LOSS_SECS  = 900   # 손절 후 15분 재진입 금지
COOLDOWN_AFTER_PROFIT_SECS = 300  # 익절 후 5분 재진입 금지
COOLDOWN_AFTER_VI_SECS    = 120   # VI 발동 후 2분 진입 금지


@dataclass
class CooldownEntry:
    reason: str           # "loss" | "profit" | "vi"
    expires_at: float     # epoch seconds


@dataclass
class DailyRiskState:
    date: str = field(default_factory=lambda: date.today().isoformat())
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    consecutive_losses: int = 0
    total_commission: float = 0.0
    is_halted: bool = False
    halt_reason: str = ""
    halt_type: str = ""   # BUG-26 FIX: "daily_loss" | "consecutive_loss" | "kosdaq_halt"
    capital: float = 0.0
    trades_per_symbol: dict = field(default_factory=dict)  # symbol → 진입 횟수
    overnight_trades_per_symbol: dict = field(default_factory=dict)
    trades_per_strategy: dict = field(default_factory=dict)
    realized_pnl_per_symbol: dict = field(default_factory=dict)


class RiskManager:
    """
    역할:
    - 모든 신규 진입 요청의 게이트키퍼
    - 일 손실 한도 = 실현 + 미실현 합산
    - 연속 손절 카운터: 손절 +1, 익절 -1
    - 시간 기반 쿨다운: 손절 15분 / 익절 5분 / VI 2분
    - 코스닥 지수 -1.5% 이하 전체 차단

    halt 후에도 청산 주문은 허용 (신규 진입만 차단).
    """

    def __init__(self, capital: float = 0.0) -> None:
        self._state = DailyRiskState(capital=capital)
        self._kosdaq_change_pct: float = 0.0
        self._cooldowns: dict[str, CooldownEntry] = {}   # symbol → CooldownEntry

    # ── 진입 승인 ─────────────────────────────────────────────────────────────

    def approve_entry(
        self,
        symbol: str,
        amount: float,
        current_positions_count: int,
        total_exposure: float,
        market_strength_ok: bool = True,
        max_symbols_override: Optional[int] = None,
        max_position_pct_override: Optional[float] = None,
        max_total_exposure_pct_override: Optional[float] = None,
        position_type: PositionType = PositionType.INTRADAY_SCALP,
        symbol_exposure: float = 0.0,
        overnight_total_exposure: Optional[float] = None,
        kosdaq_change_pct: Optional[float] = None,
        strategy_name: str = "",
        max_daily_trades_override: Optional[int] = None,
        max_trades_per_strategy_override: Optional[int] = None,
    ) -> tuple[bool, str]:
        """
        신규 진입 승인 여부. 반환: (approved, reason).
        *_override 파라미터는 MarketRegime 정책 적용 시 사용.
        """
        s = self._state
        _max_sym = max_symbols_override if max_symbols_override is not None else MAX_SYMBOLS
        _max_pos = max_position_pct_override if max_position_pct_override is not None else MAX_POSITION_PCT
        _max_exp = max_total_exposure_pct_override if max_total_exposure_pct_override is not None else MAX_TOTAL_EXPOSURE_PCT
        _max_daily_trades = max_daily_trades_override if max_daily_trades_override is not None else MAX_DAILY_TRADES
        _max_trades_per_strategy = (
            max_trades_per_strategy_override
            if max_trades_per_strategy_override is not None
            else MAX_TRADES_PER_STRATEGY
        )

        # BUG-09 FIX: capital=0 이면 비중 체크가 스킵되어 무제한 주문 가능 → 완전 차단
        if s.capital <= 0:
            return False, "자본금 미설정 또는 조회 실패 — 진입 차단 (capital=0)"

        if s.is_halted:
            return False, s.halt_reason

        symbol_pnl = float(s.realized_pnl_per_symbol.get(symbol, 0.0) or 0.0)
        if s.capital > 0 and symbol_pnl / s.capital <= -MAX_LOSS_PER_SYMBOL_PCT:
            return False, f"{symbol} 종목당 손실 한도 도달 ({symbol_pnl / s.capital:.1%})"

        if not market_strength_ok:
            return False, f"코스닥 지수 약세 ({self._kosdaq_change_pct:.1%})"

        if s.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            self._halt(f"연속 손절 {s.consecutive_losses}회", halt_type="consecutive_loss")
            return False, s.halt_reason

        if position_type == PositionType.CLOSE_BET:
            kosdaq_pct = self._kosdaq_change_pct if kosdaq_change_pct is None else kosdaq_change_pct
            if kosdaq_pct <= CLOSE_BET_MIN_KOSDAQ_CHANGE_PCT:
                return False, f"CLOSE_BET KOSDAQ 약세 ({kosdaq_pct:.1%})"
            overnight_total = total_exposure if overnight_total_exposure is None else overnight_total_exposure
            if (symbol_exposure + amount) / s.capital > OVERNIGHT_MAX_PER_SYMBOL:
                return False, f"CLOSE_BET 종목당 overnight 비중 초과 ({OVERNIGHT_MAX_PER_SYMBOL:.0%})"
            if (overnight_total + amount) / s.capital > OVERNIGHT_MAX_TOTAL:
                return False, f"CLOSE_BET 전체 overnight 비중 초과 ({OVERNIGHT_MAX_TOTAL:.0%})"
            return True, "ok"

        # 과매매 방지: 일일 최대 진입 횟수
        if s.total_trades >= _max_daily_trades:
            return False, f"일일 최대 거래 횟수 초과 ({_max_daily_trades}회)"

        # 과매매 방지: 종목별 최대 진입 횟수
        symbol_trades = s.trades_per_symbol.get(symbol, 0)
        if symbol_trades >= MAX_TRADES_PER_SYMBOL:
            return False, f"{symbol} 종목별 최대 거래 횟수 초과 ({MAX_TRADES_PER_SYMBOL}회)"

        if strategy_name:
            strategy_trades = s.trades_per_strategy.get(strategy_name, 0)
            if strategy_trades >= _max_trades_per_strategy:
                return False, f"{strategy_name} 전략별 최대 진입 횟수 초과 ({_max_trades_per_strategy}회)"

        # 쿨다운 체크 (시간 기반)
        cooldown = self._cooldowns.get(symbol)
        if cooldown and time.monotonic() < cooldown.expires_at:
            remaining = int(cooldown.expires_at - time.monotonic())
            return False, f"{symbol} 쿨다운 중 ({cooldown.reason}, {remaining}초 남음)"
        elif cooldown:
            del self._cooldowns[symbol]

        if current_positions_count >= _max_sym:
            return False, f"최대 동시 보유 종목 수 초과 ({_max_sym})"

        if s.capital > 0 and amount / s.capital > _max_pos:
            return False, f"종목당 최대 비중 초과 ({_max_pos:.0%})"

        if s.capital > 0 and total_exposure / s.capital > _max_exp:
            return False, f"전체 노출 비중 초과 ({_max_exp:.0%})"

        total_pnl_pct = (s.realized_pnl + s.unrealized_pnl) / s.capital if s.capital > 0 else 0.0
        if total_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
            self._halt(f"일 손실 한도 도달 ({total_pnl_pct:.1%})")
            return False, s.halt_reason

        return True, "ok"

    def approve_strategy_exposure(
        self,
        strategy_name: str,
        amount: float,
        strategy_exposure: float = 0.0,
    ) -> tuple[bool, str]:
        """Strategy-level exposure bucket check.

        This is intentionally separate from approve_entry so existing intraday
        behavior remains unchanged until callers opt into strategy buckets.
        """
        capital = self._state.capital
        if capital <= 0:
            return False, "자본금 미설정 또는 조회 실패 — 전략 비중 차단"
        limit = self.strategy_exposure_limit(strategy_name)
        if limit <= 0:
            return True, "ok"
        if (strategy_exposure + amount) / capital > limit:
            return False, f"{strategy_name} 전략 비중 초과 ({limit:.0%})"
        return True, "ok"

    @staticmethod
    def strategy_exposure_limit(strategy_name: str) -> float:
        limits = {
            "opening_momentum": MAX_EXPOSURE_OPENING_MOMENTUM,
            "shallow_pullback": MAX_EXPOSURE_SHALLOW_PULLBACK,
            "vwap_reclaim": MAX_EXPOSURE_VWAP_RECLAIM,
            "deep_pullback": MAX_EXPOSURE_DEEP_PULLBACK,
        }
        return limits.get(strategy_name, 0.0)

    # ── 결과 반영 ─────────────────────────────────────────────────────────────

    def record_entry(
        self,
        symbol: str,
        position_type: PositionType = PositionType.INTRADAY_SCALP,
        strategy_name: str = "",
    ) -> None:
        """진입(매수 체결) 시 호출 — 과매매 카운터 증가."""
        s = self._state
        s.total_trades += 1
        if position_type == PositionType.CLOSE_BET:
            bucket = s.overnight_trades_per_symbol
        else:
            bucket = s.trades_per_symbol
        bucket[symbol] = bucket.get(symbol, 0) + 1
        if strategy_name:
            s.trades_per_strategy[strategy_name] = s.trades_per_strategy.get(strategy_name, 0) + 1
        logger.debug("RiskManager: entry recorded %s total=%d symbol_trades=%d",
                     symbol, s.total_trades, bucket[symbol])

    def exposure_by_position_type(
        self,
        positions: dict,
        position_type: PositionType,
    ) -> float:
        return sum(
            pos.avg_price * pos.remaining_qty
            for pos in positions.values()
            if getattr(pos, "position_type", PositionType.UNKNOWN) == position_type
        )

    def symbol_exposure_by_position_type(
        self,
        positions: dict,
        symbol: str,
        position_type: PositionType,
    ) -> float:
        pos = positions.get(symbol)
        if not pos or getattr(pos, "position_type", PositionType.UNKNOWN) != position_type:
            return 0.0
        return pos.avg_price * pos.remaining_qty

    def record_trade(self, symbol: str, realized_pnl: float, commission: float,
                     is_partial: bool = False) -> None:
        s = self._state
        s.realized_pnl += realized_pnl
        s.realized_pnl_per_symbol[symbol] = (
            float(s.realized_pnl_per_symbol.get(symbol, 0.0) or 0.0) + realized_pnl
        )
        s.total_commission += commission
        if not is_partial:
            if realized_pnl > 0:
                s.win_count += 1
                s.consecutive_losses = max(0, s.consecutive_losses - 1)
                # 익절 후 5분 쿨다운
                self._set_cooldown(symbol, "profit", max(COOLDOWN_AFTER_PROFIT_SECS, REENTRY_COOLDOWN_SECS))
            else:
                s.loss_count += 1
                s.consecutive_losses += 1
                # 손절 후 15분 쿨다운
                self._set_cooldown(symbol, "loss", COOLDOWN_AFTER_LOSS_SECS)

        if s.capital > 0:
            total_pct = (s.realized_pnl + s.unrealized_pnl) / s.capital
            if total_pct <= -DAILY_LOSS_LIMIT_PCT and not s.is_halted:
                self._halt(f"일 손실 한도 도달 ({total_pct:.1%})", halt_type="daily_loss")
        logger.debug("RiskManager: realized=%.0f consecutive=%d", realized_pnl, s.consecutive_losses)

    def set_vi_cooldown(self, symbol: str) -> None:
        """VI 발동 시 2분 쿨다운."""
        self._set_cooldown(symbol, "vi", COOLDOWN_AFTER_VI_SECS)
        logger.info("RiskManager: VI cooldown set for %s", symbol)

    def update_unrealized(self, unrealized_pnl: float) -> None:
        self._state.unrealized_pnl = unrealized_pnl
        if self._state.capital > 0:
            total_pct = (self._state.realized_pnl + unrealized_pnl) / self._state.capital
            if total_pct <= -DAILY_LOSS_LIMIT_PCT and not self._state.is_halted:
                self._halt(f"일 손실 한도 실시간 도달 ({total_pct:.1%})", halt_type="daily_loss")

    def update_kosdaq(self, change_pct: float) -> None:
        self._kosdaq_change_pct = change_pct
        if change_pct <= KOSDAQ_HALT_THRESHOLD and not self._state.is_halted:
            self._halt(f"KOSDAQ 지수 급락 ({change_pct:.1%})", halt_type="kosdaq_halt")

    def initialize_capital(self, capital: float) -> None:
        self._state.capital = capital

    def manual_resume(self) -> None:
        self._state.is_halted = False
        self._state.halt_reason = ""
        logger.warning("RiskManager: halt manually released")

    # ── 상태 조회 ─────────────────────────────────────────────────────────────

    @property
    def is_halted(self) -> bool:
        return self._state.is_halted

    @property
    def state(self) -> DailyRiskState:
        return self._state

    def adaptive_min_score(self) -> float:
        """연속 손절 횟수에 따라 진입 최소 점수를 동적으로 상향."""
        losses = self._state.consecutive_losses
        if losses >= 2:
            return MIN_ENTRY_SCORE + ADAPTIVE_SCORE_LOSS_2
        elif losses >= 1:
            return MIN_ENTRY_SCORE + ADAPTIVE_SCORE_LOSS_1
        return MIN_ENTRY_SCORE

    def get_cooldown(self, symbol: str) -> Optional[CooldownEntry]:
        cd = self._cooldowns.get(symbol)
        if cd and time.monotonic() >= cd.expires_at:
            del self._cooldowns[symbol]
            return None
        return cd

    def to_dict(self) -> dict:
        s = self._state
        now = time.monotonic()
        active_cooldowns = {
            sym: {"reason": cd.reason, "remaining_secs": int(cd.expires_at - now)}
            for sym, cd in self._cooldowns.items()
            if cd.expires_at > now
        }
        return {
            "date": s.date,
            "realized_pnl": round(s.realized_pnl),
            "unrealized_pnl": round(s.unrealized_pnl),
            "total_pnl": round(s.realized_pnl + s.unrealized_pnl),
            "total_pnl_pct": round((s.realized_pnl + s.unrealized_pnl) / s.capital, 4) if s.capital else 0,
            "total_trades": s.total_trades,
            "win_count": s.win_count,
            "loss_count": s.loss_count,
            "win_rate": round(s.win_count / max(s.win_count + s.loss_count, 1), 3),
            "consecutive_losses": s.consecutive_losses,
            "adaptive_min_score": self.adaptive_min_score(),
            "total_commission": round(s.total_commission),
            "is_halted": s.is_halted,
            "halt_reason": s.halt_reason,
            "cooldowns": active_cooldowns,
            "trades_per_strategy": dict(s.trades_per_strategy),
            "realized_pnl_per_symbol": {
                sym: round(float(pnl), 2)
                for sym, pnl in s.realized_pnl_per_symbol.items()
            },
        }

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _set_cooldown(self, symbol: str, reason: str, secs: float) -> None:
        self._cooldowns[symbol] = CooldownEntry(
            reason=reason,
            expires_at=time.monotonic() + secs,
        )
        logger.info("RiskManager: %s cooldown=%s %ds", symbol, reason, secs)

    @property
    def halt_type(self) -> str:
        """BUG-26 FIX: halt 원인 유형 반환 (kill reason 매핑용)."""
        return self._state.halt_type

    def _halt(self, reason: str, halt_type: str = "unknown") -> None:
        self._state.is_halted = True
        self._state.halt_reason = reason
        self._state.halt_type = halt_type
        logger.warning("RiskManager HALTED [%s]: %s", halt_type, reason)
