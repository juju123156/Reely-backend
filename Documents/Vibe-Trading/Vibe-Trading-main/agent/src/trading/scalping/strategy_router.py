"""Intraday strategy router and conflict resolver."""

from __future__ import annotations

from datetime import time as dtime
from typing import Any

from .events import TickEvent
from .market_regime import MarketRegime
from .strategy_params import StrategyParameterStore
from .strategies.leader_rotation import LeaderContext, LeaderRotationStrategy
from .strategies.momentum_continuation import MomentumContinuationStrategy
from .strategies.opening_momentum import OpeningMomentumStrategy
from .strategies.shallow_pullback import ShallowPullbackStrategy
from .strategies.vwap_reclaim import VWAPReclaimStrategy
from .strategy_types import (
    StrategyActivation,
    StrategyCandidate,
    StrategyContext,
    StrategyMode,
    StrategyName,
    StrategySignal,
)


STRATEGY_PRIORITY = {
    StrategyName.CLOSE_BET.value: 90,
    StrategyName.OPENING_MOMENTUM.value: 80,
    StrategyName.SHALLOW_PULLBACK.value: 70,
    StrategyName.VWAP_RECLAIM.value: 60,
    StrategyName.MOMENTUM_CONTINUATION.value: 55,
    StrategyName.DEEP_PULLBACK.value: 50,
}


class StrategyConflictResolver:
    """Picks one live buy per symbol while preserving shadow diagnostics."""

    def resolve(self, signals: list[StrategySignal]) -> list[StrategySignal]:
        exits = [s for s in signals if s.side == "sell"]
        buys = [s for s in signals if s.side == "buy"]
        if exits:
            return sorted(exits, key=self._sort_key, reverse=True)

        shadow = [s for s in buys if s.shadow_only or not s.live_allowed]
        live = [s for s in buys if s.live_allowed and not s.shadow_only]
        if not live:
            return shadow

        best = sorted(live, key=self._sort_key, reverse=True)[0]
        return [*shadow, best]

    @staticmethod
    def _sort_key(signal: StrategySignal) -> tuple[float, float, float]:
        return (
            float(STRATEGY_PRIORITY.get(signal.strategy_name, 0)),
            float(signal.expected_edge_pct),
            float(signal.confidence),
        )


class IntradayStrategyRouter:
    def __init__(self, params: StrategyParameterStore | None = None) -> None:
        self._params = params or StrategyParameterStore()
        self._leader_strategy = LeaderRotationStrategy(self._params.section("leader_rotation"))
        self._opening = OpeningMomentumStrategy()
        self._shallow = ShallowPullbackStrategy(self._params.section("shallow_pullback"))
        self._vwap = VWAPReclaimStrategy(self._params.section("vwap_reclaim"))
        self._continuation = MomentumContinuationStrategy(self._params.section("momentum_continuation"))
        self._resolver = StrategyConflictResolver()
        self._last_summary: dict[str, Any] = {}

    def select_active_strategies(
        self,
        now,
        regime,
        market_context: dict | None = None,
    ) -> list[StrategyActivation]:
        if now < dtime(9, 5):
            return [
                StrategyActivation(StrategyName.OPENING_MOMENTUM, StrategyMode.SHADOW, "pre_entry_shadow_only"),
            ]
        if dtime(9, 5) <= now < dtime(9, 20):
            return [
                StrategyActivation(StrategyName.OPENING_MOMENTUM, StrategyMode.SHADOW, "opening_shadow_first"),
                StrategyActivation(StrategyName.SHALLOW_PULLBACK, StrategyMode.SHADOW, "opening_aux_shadow"),
            ]
        if dtime(9, 20) <= now < dtime(10, 30):
            return [
                StrategyActivation(StrategyName.SHALLOW_PULLBACK, StrategyMode.LIVE, "main_window"),
                StrategyActivation(StrategyName.LEADER_ROTATION, StrategyMode.LIVE, "filter_and_sizing"),
                StrategyActivation(StrategyName.MOMENTUM_CONTINUATION, StrategyMode.SHADOW, "continuation_shadow_first"),
            ]
        if dtime(10, 30) <= now < dtime(13, 0):
            return [
                StrategyActivation(StrategyName.VWAP_RECLAIM, StrategyMode.SHADOW, "midday_shadow_first"),
                StrategyActivation(StrategyName.MOMENTUM_CONTINUATION, StrategyMode.SHADOW, "continuation_shadow_first"),
                StrategyActivation(StrategyName.LEADER_ROTATION, StrategyMode.LIVE, "filter_and_sizing"),
            ]
        if dtime(13, 0) <= now < dtime(14, 50):
            return [
                StrategyActivation(StrategyName.VWAP_RECLAIM, StrategyMode.SHADOW, "late_intraday_shadow_only"),
                StrategyActivation(StrategyName.MOMENTUM_CONTINUATION, StrategyMode.SHADOW, "late_continuation_shadow_only"),
            ]
        if dtime(14, 50) <= now < dtime(15, 15):
            return [
                StrategyActivation(StrategyName.CLOSE_BET, StrategyMode.LIVE, "close_bet_window"),
            ]
        return []

    def route_tick(
        self,
        tick: TickEvent,
        symbol_state,
        context: StrategyContext,
    ) -> list[StrategySignal]:
        activations = self.select_active_strategies(context.now_time, context.regime, {})
        modes = {a.name.value: a.mode for a in activations}
        leader = self._leader_strategy.build_context(context.candidate)
        signals: list[StrategySignal] = []

        if modes.get(StrategyName.OPENING_MOMENTUM.value) is not None:
            sig = self._opening.evaluate(tick, context, leader)
            if sig:
                signals.append(self._apply_mode(sig, modes[StrategyName.OPENING_MOMENTUM.value]))
        if modes.get(StrategyName.SHALLOW_PULLBACK.value) is not None:
            sig = self._shallow.evaluate(tick, context, leader)
            if sig:
                signals.append(self._apply_mode(sig, modes[StrategyName.SHALLOW_PULLBACK.value]))
        if modes.get(StrategyName.VWAP_RECLAIM.value) is not None:
            sig = self._vwap.evaluate(tick, context, leader)
            if sig:
                signals.append(self._apply_mode(sig, modes[StrategyName.VWAP_RECLAIM.value]))
        if modes.get(StrategyName.MOMENTUM_CONTINUATION.value) is not None:
            sig = self._continuation.evaluate(tick, context, leader)
            if sig:
                signals.append(self._apply_mode(sig, modes[StrategyName.MOMENTUM_CONTINUATION.value]))

        resolved = self._resolver.resolve(signals)
        self._last_summary = self._build_summary(activations, signals, resolved, leader)
        return resolved

    def route_candidates(
        self,
        candidates,
        context: StrategyContext,
    ) -> list[StrategyCandidate]:
        activations = self.select_active_strategies(context.now_time, context.regime, {})
        active = {a.name.value: a.mode for a in activations}
        routed: list[StrategyCandidate] = []
        for c in candidates:
            leader = self._leader_strategy.build_context(c)
            if active.get(StrategyName.OPENING_MOMENTUM.value) and leader.allow_opening_momentum:
                routed.append(StrategyCandidate(
                    strategy_name=StrategyName.OPENING_MOMENTUM.value,
                    symbol=c.symbol,
                    mode=active[StrategyName.OPENING_MOMENTUM.value],
                    priority=STRATEGY_PRIORITY[StrategyName.OPENING_MOMENTUM.value],
                    reason=leader.reason,
                    metrics={"leader_rank": leader.leader_rank, "leader_score": leader.leader_score},
                ))
            if active.get(StrategyName.SHALLOW_PULLBACK.value) and leader.allow_shallow_pullback:
                routed.append(StrategyCandidate(
                    strategy_name=StrategyName.SHALLOW_PULLBACK.value,
                    symbol=c.symbol,
                    mode=active[StrategyName.SHALLOW_PULLBACK.value],
                    priority=STRATEGY_PRIORITY[StrategyName.SHALLOW_PULLBACK.value],
                    reason=leader.reason,
                    metrics={"leader_rank": leader.leader_rank, "leader_score": leader.leader_score},
                ))
            elif active.get(StrategyName.SHALLOW_PULLBACK.value) and leader.allow_leader_shadow:
                routed.append(StrategyCandidate(
                    strategy_name="leader_only_shallow_pullback_near_miss",
                    symbol=c.symbol,
                    mode=StrategyMode.SHADOW,
                    priority=STRATEGY_PRIORITY[StrategyName.SHALLOW_PULLBACK.value] - 1,
                    reason="leader_score_60_70_shadow_only",
                    metrics={"leader_rank": leader.leader_rank, "leader_score": leader.leader_score},
                ))
            if active.get(StrategyName.VWAP_RECLAIM.value):
                routed.append(StrategyCandidate(
                    strategy_name=StrategyName.VWAP_RECLAIM.value,
                    symbol=c.symbol,
                    mode=active[StrategyName.VWAP_RECLAIM.value],
                    priority=STRATEGY_PRIORITY[StrategyName.VWAP_RECLAIM.value],
                    reason="candidate_watch",
                    metrics={"leader_rank": leader.leader_rank, "leader_score": leader.leader_score},
                ))
            if active.get(StrategyName.MOMENTUM_CONTINUATION.value) and leader.leader_rank <= 3:
                routed.append(StrategyCandidate(
                    strategy_name=StrategyName.MOMENTUM_CONTINUATION.value,
                    symbol=c.symbol,
                    mode=StrategyMode.SHADOW,
                    priority=STRATEGY_PRIORITY[StrategyName.MOMENTUM_CONTINUATION.value],
                    reason="top3_continuation_watch",
                    metrics={"leader_rank": leader.leader_rank, "leader_score": leader.leader_score},
                ))
        return routed

    @property
    def last_summary(self) -> dict[str, Any]:
        return dict(self._last_summary)

    @staticmethod
    def _apply_mode(signal: StrategySignal, mode: StrategyMode) -> StrategySignal:
        if mode == StrategyMode.DISABLED:
            return StrategySignal(
                **{**signal.__dict__, "live_allowed": False, "shadow_only": True, "reason": "strategy_disabled"}
            )
        if mode == StrategyMode.SHADOW:
            return StrategySignal(
                **{**signal.__dict__, "live_allowed": False, "shadow_only": True}
            )
        return signal

    @staticmethod
    def _build_summary(
        activations: list[StrategyActivation],
        raw_signals: list[StrategySignal],
        resolved: list[StrategySignal],
        leader: LeaderContext,
    ) -> dict[str, Any]:
        return {
            "active_strategies": [a.name.value for a in activations],
            "shadow_strategies": [a.name.value for a in activations if a.mode == StrategyMode.SHADOW],
            "live_strategies": [a.name.value for a in activations if a.mode == StrategyMode.LIVE],
            "signal_count": len(raw_signals),
            "live_signal_count": len([s for s in resolved if s.live_allowed and not s.shadow_only]),
            "shadow_signal_count": len([s for s in resolved if s.shadow_only or not s.live_allowed]),
            "top_reject_reason": next((s.reason for s in raw_signals if s.entry_price is None), "none"),
            "leader_rank": leader.leader_rank,
            "leader_score": leader.leader_score,
        }
