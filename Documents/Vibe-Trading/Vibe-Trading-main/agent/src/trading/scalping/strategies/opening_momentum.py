"""Opening momentum strategy, shadow-first."""

from __future__ import annotations

from datetime import time as dtime
from typing import Any

from ..constants import EXPECTED_ENTRY_SLIPPAGE_PCT, EXPECTED_EXIT_SLIPPAGE_PCT
from ..events import TickEvent
from ..position_type import PositionType
from ..strategy_types import StrategyContext, StrategySignal
from .leader_rotation import LeaderContext


class OpeningMomentumStrategy:
    name = "opening_momentum"

    def evaluate(
        self,
        tick: TickEvent,
        context: StrategyContext,
        leader: LeaderContext,
    ) -> StrategySignal | None:
        now = context.now_time
        if not (dtime(9, 5) <= now < dtime(9, 20)):
            return None
        if not leader.allow_opening_momentum:
            return self._reject(tick, "not_leader", context, leader)
        candidate = context.candidate
        if candidate is None:
            return self._reject(tick, "missing_candidate", context, leader)

        change_pct = float(getattr(candidate, "change_pct", 0.0) or 0.0)
        if change_pct < 0.03 or change_pct > 0.12:
            return self._reject(tick, "change_pct_out_of_range", context, leader)

        snap = context.signal_snapshot
        vwap_gap = float(snap.get("vwap_gap", 0.0) or 0.0)
        exec_strength = float(snap.get("exec_strength", 0.0) or 0.0)
        spread_pct = self._spread_pct(tick)
        if vwap_gap < 0:
            return self._reject(tick, "below_vwap", context, leader)
        if exec_strength < 110:
            return self._reject(tick, "exec_strength_below", context, leader)
        if spread_pct > 0.0025:
            return self._reject(tick, "spread_too_wide", context, leader)

        edge = min(0.012, max(0.006, change_pct * 0.12)) - self._cost_pct()
        live_allowed = False  # shadow-first until enough evidence is accumulated.
        return StrategySignal(
            strategy_name=self.name,
            symbol=tick.symbol,
            side="buy",
            confidence=min(0.95, leader.leader_score / 100.0),
            expected_edge_pct=edge,
            entry_price=tick.ask1_price or tick.price,
            stop_price=tick.price * 0.993,
            take_profit_price=tick.price * 1.010,
            position_type=PositionType.INTRADAY_SCALP,
            live_allowed=live_allowed,
            shadow_only=True,
            reason="opening_momentum_shadow",
            metrics=self._metrics(context, leader, spread_pct, reject_reason=None),
        )

    def _reject(
        self,
        tick: TickEvent,
        reason: str,
        context: StrategyContext,
        leader: LeaderContext,
    ) -> StrategySignal:
        return StrategySignal(
            strategy_name=self.name,
            symbol=tick.symbol,
            side="buy",
            confidence=0.0,
            expected_edge_pct=0.0,
            entry_price=None,
            stop_price=None,
            take_profit_price=None,
            position_type=PositionType.INTRADAY_SCALP,
            live_allowed=False,
            shadow_only=True,
            reason=reason,
            metrics=self._metrics(context, leader, self._spread_pct(tick), reject_reason=reason),
        )

    @staticmethod
    def _spread_pct(tick: TickEvent) -> float:
        if tick.price <= 0 or tick.ask1_price <= 0 or tick.bid1_price <= 0:
            return 0.0
        return max(0.0, (tick.ask1_price - tick.bid1_price) / tick.price)

    @staticmethod
    def _cost_pct() -> float:
        return EXPECTED_ENTRY_SLIPPAGE_PCT + EXPECTED_EXIT_SLIPPAGE_PCT

    @staticmethod
    def _metrics(
        context: StrategyContext,
        leader: LeaderContext,
        spread_pct: float,
        reject_reason: str | None,
    ) -> dict[str, Any]:
        snap = context.signal_snapshot
        return {
            "leader_rank": leader.leader_rank,
            "leader_score": leader.leader_score,
            "change_pct": float(getattr(context.candidate, "change_pct", 0.0) or 0.0),
            "vwap_gap": float(snap.get("vwap_gap", 0.0) or 0.0),
            "exec_strength": float(snap.get("exec_strength", 0.0) or 0.0),
            "spread_pct": spread_pct,
            "reject_reason": reject_reason,
        }
