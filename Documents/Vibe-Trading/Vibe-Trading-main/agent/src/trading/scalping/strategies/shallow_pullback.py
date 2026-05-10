"""Leader shallow pullback strategy."""

from __future__ import annotations

from datetime import time as dtime
from typing import Any

from ..constants import (
    SHALLOW_ENTRY_EXEC_MIN,
    SHALLOW_ENTRY_OB_MIN,
    SHALLOW_ENTRY_SCORE,
    SHALLOW_ENTRY_VWAP_MIN_GAP,
    SHALLOW_PULLBACK_MAX_PCT,
    SHALLOW_PULLBACK_MIN_PCT,
)
from ..events import TickEvent
from ..position_type import PositionType
from ..strategy_types import StrategyContext, StrategySignal
from .leader_rotation import LeaderContext


class ShallowPullbackStrategy:
    name = "shallow_pullback"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = params or {}

    def evaluate(
        self,
        tick: TickEvent,
        context: StrategyContext,
        leader: LeaderContext,
    ) -> StrategySignal | None:
        now = context.now_time
        if not (dtime(9, 20) <= now < dtime(10, 30)):
            return None
        if not leader.allow_shallow_pullback:
            return self._reject(tick, "not_leader", context, leader)

        snap = context.signal_snapshot
        pullback_pct = float(snap.get("pullback_pct", 0.0) or 0.0)
        exec_strength = float(snap.get("exec_strength", 0.0) or 0.0)
        ob_imbalance = float(snap.get("ob_imbalance", 1.0) or 1.0)
        vwap_gap = float(snap.get("vwap_gap", 0.0) or 0.0)
        score = self._score(snap, leader)
        spread_pct = self._spread_pct(tick)

        min_pullback = float(self._params.get("pullback_min_pct", SHALLOW_PULLBACK_MIN_PCT))
        max_pullback = float(self._params.get("pullback_max_pct", 0.012))
        min_exec = float(self._params.get("entry_exec_min", SHALLOW_ENTRY_EXEC_MIN))
        min_ob = float(self._params.get("entry_ob_min", SHALLOW_ENTRY_OB_MIN))
        min_vwap_gap = float(self._params.get("entry_vwap_min_gap", SHALLOW_ENTRY_VWAP_MIN_GAP))
        min_score = float(self._params.get("entry_score", SHALLOW_ENTRY_SCORE))
        max_spread = float(self._params.get("max_spread_pct", 0.003))

        if not (min_pullback <= pullback_pct <= max_pullback):
            return self._reject(tick, "pullback_depth_out_of_range", context, leader)
        if exec_strength < min_exec:
            return self._reject(tick, "exec_strength_below", context, leader)
        if ob_imbalance < min_ob:
            return self._reject(tick, "ob_imbalance_weak", context, leader)
        if vwap_gap < min_vwap_gap:
            return self._reject(tick, "below_vwap_tolerance", context, leader)
        if spread_pct > max_spread:
            return self._reject(tick, "spread_too_wide", context, leader)
        if score < min_score:
            return self._reject(tick, "score_below", context, leader)

        edge = min(0.015, max(0.007, pullback_pct + 0.006)) - context.cost_floor_pct
        return StrategySignal(
            strategy_name=self.name,
            symbol=tick.symbol,
            side="buy",
            confidence=min(0.95, score / 100.0),
            expected_edge_pct=edge,
            entry_price=tick.ask1_price or tick.price,
            stop_price=tick.price * 0.992,
            take_profit_price=tick.price * 1.012,
            position_type=PositionType.INTRADAY_SCALP,
            live_allowed=edge > 0 and context.market_ok,
            shadow_only=False,
            reason=(
                f"shallow_pullback rank={leader.leader_rank} pullback={pullback_pct:.4f} "
                f"score={score:.1f}"
            ),
            metrics=self._metrics(context, leader, score, spread_pct, reject_reason=None),
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
            metrics=self._metrics(context, leader, 0.0, self._spread_pct(tick), reject_reason=reason),
        )

    @staticmethod
    def _score(snap: dict, leader: LeaderContext) -> float:
        exec_strength = float(snap.get("exec_strength", 0.0) or 0.0)
        vol_ratio = float(snap.get("vol_ratio", 0.0) or 0.0)
        vwap_gap = float(snap.get("vwap_gap", 0.0) or 0.0)
        ob_imbalance = float(snap.get("ob_imbalance", 1.0) or 1.0)
        return round(
            min(exec_strength / 150.0, 1.0) * 35.0
            + min(vol_ratio / 3.0, 1.0) * 20.0
            + (20.0 if vwap_gap >= 0 else max(0.0, 20.0 + vwap_gap * 4000.0))
            + min(ob_imbalance / 1.5, 1.0) * 10.0
            + min(leader.leader_score / 100.0, 1.0) * 15.0,
            1,
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
        score: float,
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
            "ob_imbalance": float(snap.get("ob_imbalance", 1.0) or 1.0),
            "score": score,
            "spread_pct": spread_pct,
            "reject_reason": reject_reason,
            "leader_max_pullback_pct": SHALLOW_PULLBACK_MAX_PCT,
        }
