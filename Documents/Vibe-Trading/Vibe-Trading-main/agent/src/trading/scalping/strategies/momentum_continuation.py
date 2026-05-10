"""Momentum continuation shadow strategy."""

from __future__ import annotations

from datetime import time as dtime
from typing import Any

from ..constants import (
    MOMENTUM_CONTINUATION_MAX_PULLBACK_PCT,
    MOMENTUM_CONTINUATION_MAX_SPREAD_PCT,
    MOMENTUM_CONTINUATION_MIN_EXEC,
    MOMENTUM_CONTINUATION_MIN_VOL_RATIO,
)
from ..events import TickEvent
from ..position_type import PositionType
from ..strategy_types import StrategyContext, StrategySignal
from .leader_rotation import LeaderContext


class MomentumContinuationStrategy:
    """Tracks leaders that keep pressure near highs without a classic pullback."""

    name = "momentum_continuation"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = params or {}

    def evaluate(
        self,
        tick: TickEvent,
        context: StrategyContext,
        leader: LeaderContext,
    ) -> StrategySignal | None:
        now = context.now_time
        if not (dtime(9, 20) <= now < dtime(14, 50)):
            return None
        if leader.leader_rank > 3:
            return self._reject(tick, "not_top3_leader", context, leader)

        snap = context.signal_snapshot
        pullback_pct = float(snap.get("pullback_pct", 0.0) or 0.0)
        exec_strength = float(snap.get("exec_strength", 0.0) or 0.0)
        vol_ratio = float(snap.get("vol_ratio", 0.0) or 0.0)
        vwap_gap = float(snap.get("vwap_gap", 0.0) or 0.0)
        spread_pct = self._spread_pct(tick)

        if pullback_pct > float(self._params.get("max_pullback_pct", MOMENTUM_CONTINUATION_MAX_PULLBACK_PCT)):
            return self._reject(tick, "pullback_too_deep_for_continuation", context, leader)
        if vwap_gap < 0:
            return self._reject(tick, "below_vwap", context, leader)
        if exec_strength < float(self._params.get("min_exec_strength", MOMENTUM_CONTINUATION_MIN_EXEC)):
            return self._reject(tick, "exec_strength_below", context, leader)
        if vol_ratio < float(self._params.get("min_vol_ratio", MOMENTUM_CONTINUATION_MIN_VOL_RATIO)):
            return self._reject(tick, "vol_ratio_below", context, leader)
        if spread_pct > float(self._params.get("max_spread_pct", MOMENTUM_CONTINUATION_MAX_SPREAD_PCT)):
            return self._reject(tick, "spread_too_wide", context, leader)

        edge = min(0.010, max(0.005, vwap_gap + 0.004)) - context.cost_floor_pct
        return StrategySignal(
            strategy_name=self.name,
            symbol=tick.symbol,
            side="buy",
            confidence=min(0.82, 0.35 + min(exec_strength / 160.0, 1.0) * 0.25 + min(vol_ratio / 3.0, 1.0) * 0.2),
            expected_edge_pct=edge,
            entry_price=tick.ask1_price or tick.price,
            stop_price=tick.price * 0.993,
            take_profit_price=tick.price * 1.009,
            position_type=PositionType.INTRADAY_SCALP,
            live_allowed=False,
            shadow_only=True,
            reason="momentum_continuation_shadow",
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
            "pullback_pct": float(snap.get("pullback_pct", 0.0) or 0.0),
            "exec_strength": float(snap.get("exec_strength", 0.0) or 0.0),
            "vol_ratio": float(snap.get("vol_ratio", 0.0) or 0.0),
            "vwap_gap": float(snap.get("vwap_gap", 0.0) or 0.0),
            "spread_pct": spread_pct,
            "reject_reason": reject_reason,
            "promotion_policy": "shadow_first_min_50_or_100_samples",
        }
