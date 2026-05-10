"""Regime score, runtime permission, and execution-quality gates.

This module is intentionally side-effect free.  The bot owns persistence and
order execution; these classes only turn observed market/execution facts into
auditable decisions.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RuntimeRegime(Enum):
    NO_TRADE = "no_trade"
    CONFIRMING = "confirming"
    WEAK = "weak"
    CHOPPY = "choppy"
    NORMAL = "normal"
    STRONG = "strong"
    TRENDING = "trending"


@dataclass(frozen=True)
class RegimeInputs:
    index_trend: float = 0.5
    top_leader_persistence: float = 0.5
    vwap_hold_ratio: float = 0.5
    follow_through_ratio: float = 0.5
    breakout_success_ratio: float = 0.5
    fake_breakout_ratio: float = 0.5
    spread_stability: float = 0.5
    vi_density: float = 0.0
    stale_tick_ratio: float = 0.0
    execution_quality_score: float = 0.7
    orderbook_stability: float = 0.5
    aggressive_buy_ratio: float = 0.5
    aggressive_sell_ratio: float = 0.5
    leader_rotation_speed: float = 0.5
    liquidity_concentration: float = 0.5
    upper_tail_ratio: float = 0.5
    failed_breakout_speed: float = 0.5
    confirming: bool = False


@dataclass(frozen=True)
class RegimeSnapshot:
    regime: RuntimeRegime
    score: float
    components: dict[str, float]
    changed_at: float
    previous_regime: str = ""
    hard_shift_triggered: bool = False
    regime_shift_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_regime": self.regime.value,
            "regime_score": round(self.score, 2),
            "regime_components": {k: round(v, 4) for k, v in self.components.items()},
            "regime_changed_at": self.changed_at,
            "previous_regime": self.previous_regime,
            "hard_shift_triggered": self.hard_shift_triggered,
            "regime_shift_reason": self.regime_shift_reason,
        }


@dataclass(frozen=True)
class ExecutionQualityInputs:
    slippage_pct: float = 0.0
    partial_fill_rate: float = 0.0
    timeout_rate: float = 0.0
    stale_tick_ratio: float = 0.0
    stale_feature_ratio: float = 0.0
    spread_widening_ratio: float = 0.0
    orderbook_collapse_ratio: float = 0.0
    quote_gap_ratio: float = 0.0
    aggressive_sell_spike: float = 0.0
    api_latency_ms: float = 0.0
    fill_probability: float = 1.0
    quote_age_ms: float = 0.0
    quote_jitter_ms: float = 0.0
    websocket_gap_ms: float = 0.0
    order_rtt_ms: float = 0.0
    top_of_book_missing: bool = False
    depth_levels_available: int = 1


@dataclass(frozen=True)
class ExecutionQualitySnapshot:
    score: float
    components: dict[str, float]
    blocked: bool
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_quality_score": round(self.score, 4),
            "execution_quality_components": {k: round(v, 4) for k, v in self.components.items()},
            "execution_quality_blocked": self.blocked,
            "execution_quality_blocked_reason": self.blocked_reason,
        }


class LatencyState(Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGER = "DANGER"


@dataclass(frozen=True)
class QuoteHealthSnapshot:
    quote_age_ms: float = 0.0
    tick_age_ms: float = 0.0
    orderbook_age_sec: float = 0.0
    quote_jitter_ms: float = 0.0
    websocket_gap_ms: float = 0.0
    order_rtt_ms: float = 0.0
    spread_pct: float = 0.0
    top_of_book_missing: bool = False
    depth_levels_available: int = 1
    latency_state: LatencyState = LatencyState.SAFE
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "quote_age_ms": round(self.quote_age_ms, 2),
            "tick_age_ms": round(self.tick_age_ms, 2),
            "orderbook_age_sec": round(self.orderbook_age_sec, 4),
            "quote_jitter_ms": round(self.quote_jitter_ms, 2),
            "websocket_gap_ms": round(self.websocket_gap_ms, 2),
            "order_rtt_ms": round(self.order_rtt_ms, 2),
            "spread_pct": round(self.spread_pct, 5),
            "top_of_book_missing": self.top_of_book_missing,
            "depth_levels_available": self.depth_levels_available,
            "latency_state": self.latency_state.value,
            "blocked_reason": self.blocked_reason,
        }


class QuoteHealthMonitor:
    def classify(
        self,
        *,
        quote_age_ms: float = 0.0,
        tick_age_ms: float = 0.0,
        orderbook_age_sec: float = 0.0,
        quote_jitter_ms: float = 0.0,
        websocket_gap_ms: float = 0.0,
        order_rtt_ms: float = 0.0,
        spread_pct: float = 0.0,
        top_of_book_missing: bool = False,
        depth_levels_available: int = 1,
    ) -> QuoteHealthSnapshot:
        reason = ""
        state = LatencyState.SAFE
        if (
            tick_age_ms > 5000
            or orderbook_age_sec > 3.0
            or quote_age_ms > 3000
            or top_of_book_missing
        ):
            state = LatencyState.DANGER
            if tick_age_ms > 5000:
                reason = "stale_tick"
            elif orderbook_age_sec > 3.0:
                reason = "stale_orderbook"
            elif quote_age_ms > 3000:
                reason = "stale_quote"
            else:
                reason = "top_of_book_missing"
        elif (
            tick_age_ms > 3000
            or orderbook_age_sec > 1.0
            or quote_age_ms > 1000
            or quote_jitter_ms > 1000
            or websocket_gap_ms > 1500
            or order_rtt_ms > 1000
            or depth_levels_available < 3
        ):
            state = LatencyState.CAUTION
            reason = "quote_health_degraded"
        return QuoteHealthSnapshot(
            quote_age_ms=quote_age_ms,
            tick_age_ms=tick_age_ms,
            orderbook_age_sec=orderbook_age_sec,
            quote_jitter_ms=quote_jitter_ms,
            websocket_gap_ms=websocket_gap_ms,
            order_rtt_ms=order_rtt_ms,
            spread_pct=spread_pct,
            top_of_book_missing=top_of_book_missing,
            depth_levels_available=depth_levels_available,
            latency_state=state,
            blocked_reason=reason,
        )


@dataclass(frozen=True)
class RegimePolicy:
    regime: RuntimeRegime
    live_strategies: tuple[str, ...] = ()
    small_live_strategies: tuple[str, ...] = ()
    blocked_strategies: tuple[str, ...] = ()
    shadow_strategies: tuple[str, ...] = ()
    max_daily_trades: int = 0
    max_trades_per_strategy: int = 0
    position_size_ratio: float = 0.0
    first_loss_pause: bool = False
    consecutive_loss_pause: int = 0
    take_profit_pct: float = 0.008
    stop_loss_pct: float = -0.006
    time_stop_sec: int = 180


@dataclass(frozen=True)
class RuntimePermissionDecision:
    strategy: str
    promotion_state: str
    regime: str
    runtime_permission: str
    allowed: bool
    blocked_reason: str = ""
    allowed_size_ratio: float = 0.0
    max_daily_trades: int = 0
    max_trades_per_strategy: int = 0
    take_profit_pct: float = 0.0
    stop_loss_pct: float = 0.0
    time_stop_sec: int = 0
    hard_shift_triggered: bool = False
    execution_quality_score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_REGIME_POLICIES: dict[RuntimeRegime, RegimePolicy] = {
    RuntimeRegime.NO_TRADE: RegimePolicy(RuntimeRegime.NO_TRADE),
    RuntimeRegime.CONFIRMING: RegimePolicy(RuntimeRegime.CONFIRMING),
    RuntimeRegime.WEAK: RegimePolicy(
        RuntimeRegime.WEAK,
        live_strategies=("leader_only_shallow_pullback",),
        max_daily_trades=1,
        max_trades_per_strategy=1,
        position_size_ratio=0.10,
        first_loss_pause=True,
        take_profit_pct=0.008,
        stop_loss_pct=-0.006,
        time_stop_sec=180,
    ),
    RuntimeRegime.CHOPPY: RegimePolicy(
        RuntimeRegime.CHOPPY,
        live_strategies=("leader_only_shallow_pullback",),
        blocked_strategies=("vwap_reclaim", "momentum_continuation", "opening_momentum"),
        max_daily_trades=1,
        max_trades_per_strategy=1,
        position_size_ratio=0.10,
        first_loss_pause=True,
        take_profit_pct=0.008,
        stop_loss_pct=-0.006,
        time_stop_sec=180,
    ),
    RuntimeRegime.NORMAL: RegimePolicy(
        RuntimeRegime.NORMAL,
        live_strategies=("leader_only_shallow_pullback",),
        small_live_strategies=("vwap_reclaim",),
        shadow_strategies=("momentum_continuation", "opening_momentum"),
        max_daily_trades=2,
        max_trades_per_strategy=1,
        position_size_ratio=0.15,
        consecutive_loss_pause=2,
        take_profit_pct=0.008,
        stop_loss_pct=-0.006,
        time_stop_sec=180,
    ),
    RuntimeRegime.STRONG: RegimePolicy(
        RuntimeRegime.STRONG,
        live_strategies=("leader_only_shallow_pullback",),
        small_live_strategies=("vwap_reclaim",),
        shadow_strategies=("momentum_continuation", "opening_momentum"),
        max_daily_trades=3,
        max_trades_per_strategy=2,
        position_size_ratio=0.20,
        consecutive_loss_pause=3,
        take_profit_pct=0.008,
        stop_loss_pct=-0.006,
        time_stop_sec=180,
    ),
    RuntimeRegime.TRENDING: RegimePolicy(
        RuntimeRegime.TRENDING,
        live_strategies=("leader_only_shallow_pullback",),
        small_live_strategies=("vwap_reclaim", "momentum_continuation"),
        shadow_strategies=("opening_momentum",),
        max_daily_trades=3,
        max_trades_per_strategy=2,
        position_size_ratio=0.20,
        consecutive_loss_pause=3,
        take_profit_pct=0.008,
        stop_loss_pct=-0.006,
        time_stop_sec=180,
    ),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class ExecutionQualityGate:
    def __init__(self, min_score: float = 0.45) -> None:
        self.min_score = min_score

    def score(self, inputs: ExecutionQualityInputs) -> ExecutionQualitySnapshot:
        components = {
            "slippage_quality": 1.0 - min(1.0, max(0.0, inputs.slippage_pct) / 0.003),
            "partial_fill_quality": 1.0 - _clamp01(inputs.partial_fill_rate),
            "timeout_quality": 1.0 - _clamp01(inputs.timeout_rate),
            "stale_tick_quality": 1.0 - _clamp01(inputs.stale_tick_ratio),
            "stale_feature_quality": 1.0 - _clamp01(inputs.stale_feature_ratio),
            "spread_quality": 1.0 - _clamp01(inputs.spread_widening_ratio),
            "orderbook_quality": 1.0 - _clamp01(inputs.orderbook_collapse_ratio),
            "quote_gap_quality": 1.0 - _clamp01(inputs.quote_gap_ratio),
            "sell_pressure_quality": 1.0 - _clamp01(inputs.aggressive_sell_spike),
            "latency_quality": 1.0 - min(1.0, max(0.0, inputs.api_latency_ms) / 1000.0),
            "fill_probability": _clamp01(inputs.fill_probability),
            "quote_freshness_quality": 1.0 - min(1.0, max(inputs.quote_age_ms, inputs.websocket_gap_ms) / 5000.0),
            "quote_jitter_quality": 1.0 - min(1.0, max(0.0, inputs.quote_jitter_ms) / 3000.0),
            "order_rtt_quality": 1.0 - min(1.0, max(0.0, inputs.order_rtt_ms) / 2000.0),
            "depth_availability": min(1.0, max(0, inputs.depth_levels_available) / 3.0),
        }
        weights = {
            "slippage_quality": 0.12,
            "partial_fill_quality": 0.08,
            "timeout_quality": 0.12,
            "stale_tick_quality": 0.14,
            "stale_feature_quality": 0.12,
            "spread_quality": 0.10,
            "orderbook_quality": 0.08,
            "quote_gap_quality": 0.06,
            "sell_pressure_quality": 0.06,
            "latency_quality": 0.05,
            "fill_probability": 0.07,
            "quote_freshness_quality": 0.04,
            "quote_jitter_quality": 0.02,
            "order_rtt_quality": 0.02,
            "depth_availability": 0.02,
        }
        weight_sum = sum(weights.values()) or 1.0
        score = sum(components[k] * w for k, w in weights.items()) / weight_sum
        blocked_reason = ""
        if inputs.top_of_book_missing:
            blocked_reason = "top_of_book_missing"
        elif inputs.quote_age_ms > 3000:
            blocked_reason = "stale_quote"
        elif inputs.websocket_gap_ms > 5000:
            blocked_reason = "websocket_gap"
        elif inputs.depth_levels_available < 1:
            blocked_reason = "empty_orderbook_depth"
        elif inputs.stale_tick_ratio >= 0.8:
            blocked_reason = "stale_tick_repeated"
        elif inputs.timeout_rate >= 0.5:
            blocked_reason = "order_timeout_repeated"
        elif inputs.slippage_pct > 0.003:
            blocked_reason = "slippage_exceeded"
        elif score < self.min_score:
            blocked_reason = "execution_quality_low"
        return ExecutionQualitySnapshot(score=score, components=components, blocked=bool(blocked_reason), blocked_reason=blocked_reason)


class RegimeScoreEngine:
    """Score-based intraday regime classifier."""

    def __init__(self) -> None:
        now = time.time()
        self._last = RegimeSnapshot(RuntimeRegime.CONFIRMING, 0.0, {}, now)

    def update(self, inputs: RegimeInputs, now: float | None = None) -> RegimeSnapshot:
        now = now or time.time()
        components = {
            "index_trend": _clamp01(inputs.index_trend),
            "top_leader_persistence": _clamp01(inputs.top_leader_persistence),
            "vwap_hold_ratio": _clamp01(inputs.vwap_hold_ratio),
            "follow_through_ratio": _clamp01(inputs.follow_through_ratio),
            "breakout_success_ratio": _clamp01(inputs.breakout_success_ratio),
            "fake_breakout_quality": 1.0 - _clamp01(inputs.fake_breakout_ratio),
            "spread_stability": _clamp01(inputs.spread_stability),
            "vi_quality": 1.0 - _clamp01(inputs.vi_density),
            "stale_tick_quality": 1.0 - _clamp01(inputs.stale_tick_ratio),
            "execution_quality_score": _clamp01(inputs.execution_quality_score),
            "orderbook_stability": _clamp01(inputs.orderbook_stability),
            "aggressive_flow": _clamp01(inputs.aggressive_buy_ratio) * (1.0 - _clamp01(inputs.aggressive_sell_ratio)),
            "leader_rotation_quality": 1.0 - _clamp01(inputs.leader_rotation_speed),
            "liquidity_concentration": _clamp01(inputs.liquidity_concentration),
            "upper_tail_quality": 1.0 - _clamp01(inputs.upper_tail_ratio),
            "failed_breakout_quality": 1.0 - _clamp01(inputs.failed_breakout_speed),
        }
        weights = {
            "index_trend": 0.07,
            "top_leader_persistence": 0.13,
            "vwap_hold_ratio": 0.08,
            "follow_through_ratio": 0.08,
            "breakout_success_ratio": 0.12,
            "fake_breakout_quality": 0.11,
            "spread_stability": 0.07,
            "vi_quality": 0.04,
            "stale_tick_quality": 0.06,
            "execution_quality_score": 0.10,
            "orderbook_stability": 0.04,
            "aggressive_flow": 0.03,
            "leader_rotation_quality": 0.02,
            "liquidity_concentration": 0.02,
            "upper_tail_quality": 0.02,
            "failed_breakout_quality": 0.01,
        }
        score = sum(components[k] * w for k, w in weights.items()) * 100.0
        hard_shift, reason = self._hard_shift(inputs, components)
        if inputs.confirming:
            regime = RuntimeRegime.CONFIRMING
        elif hard_shift:
            regime = RuntimeRegime.NO_TRADE if reason in {"stale_tick_spike", "execution_quality_collapse"} else RuntimeRegime.CHOPPY
        elif inputs.fake_breakout_ratio >= 0.55 and inputs.breakout_success_ratio < 0.35:
            regime = RuntimeRegime.CHOPPY
        elif score < 20:
            regime = RuntimeRegime.NO_TRADE
        elif score < 40:
            regime = RuntimeRegime.CHOPPY if inputs.fake_breakout_ratio >= 0.55 or inputs.breakout_success_ratio < 0.35 else RuntimeRegime.WEAK
        elif score < 60:
            regime = RuntimeRegime.NORMAL
        elif score < 80:
            regime = RuntimeRegime.STRONG
        else:
            regime = RuntimeRegime.TRENDING

        changed = regime != self._last.regime
        snapshot = RegimeSnapshot(
            regime=regime,
            score=score,
            components=components,
            changed_at=now if changed else self._last.changed_at,
            previous_regime=self._last.regime.value if changed else self._last.previous_regime,
            hard_shift_triggered=hard_shift,
            regime_shift_reason=reason if hard_shift or changed else "",
        )
        self._last = snapshot
        return snapshot

    @staticmethod
    def _hard_shift(inputs: RegimeInputs, components: dict[str, float]) -> tuple[bool, str]:
        if inputs.stale_tick_ratio >= 0.5:
            return True, "stale_tick_spike"
        if inputs.execution_quality_score < 0.35:
            return True, "execution_quality_collapse"
        if inputs.fake_breakout_ratio >= 0.70:
            return True, "fake_breakout_spike"
        if inputs.breakout_success_ratio <= 0.20 and inputs.failed_breakout_speed >= 0.65:
            return True, "breakout_success_collapse"
        if inputs.top_leader_persistence <= 0.20 and inputs.leader_rotation_speed >= 0.75:
            return True, "leader_persistence_collapse"
        if components["spread_stability"] <= 0.20:
            return True, "spread_widening"
        if inputs.aggressive_sell_ratio >= 0.80:
            return True, "aggressive_sell_spike"
        return False, ""


class RuntimePermissionGate:
    def __init__(
        self,
        policies: dict[RuntimeRegime, RegimePolicy] | None = None,
        *,
        min_tick_quality_sec: float = 5.0,
        min_feature_quality_sec: float = 5.0,
    ) -> None:
        self.policies = policies or DEFAULT_REGIME_POLICIES
        self.min_tick_quality_sec = min_tick_quality_sec
        self.min_feature_quality_sec = min_feature_quality_sec

    def evaluate(
        self,
        *,
        strategy: str,
        promotion_state: Any,
        regime: RegimeSnapshot,
        execution_quality: ExecutionQualitySnapshot,
        market_phase: str = "",
        last_tick_age_sec: float | None = None,
        stale_feature_age_sec: float | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> RuntimePermissionDecision:
        state = getattr(promotion_state, "value", str(promotion_state))
        policy = self.policies.get(regime.regime, self.policies[RuntimeRegime.NO_TRADE])
        extra = {"market_phase": market_phase, "metrics": metrics or {}}

        if state in {"disabled", "paused"}:
            return self._blocked(strategy, state, regime, policy, execution_quality, "promotion_state_blocked", extra)
        if state not in {"dry_run_live", "small_live", "normal_live"}:
            return self._blocked(strategy, state, regime, policy, execution_quality, "promotion_gate_shadow_only", extra, permission="shadow_only")
        if regime.regime in {RuntimeRegime.NO_TRADE, RuntimeRegime.CONFIRMING}:
            permission = "shadow_only" if regime.regime == RuntimeRegime.CONFIRMING else "blocked"
            return self._blocked(strategy, state, regime, policy, execution_quality, f"regime_{regime.regime.value}", extra, permission=permission)
        if regime.hard_shift_triggered and strategy in {"momentum_continuation", "opening_momentum", "vwap_reclaim"}:
            return self._blocked(strategy, state, regime, policy, execution_quality, "hard_regime_shift", extra)
        if last_tick_age_sec is not None and last_tick_age_sec >= self.min_tick_quality_sec:
            return self._blocked(strategy, state, regime, policy, execution_quality, "stale_tick", extra)
        if stale_feature_age_sec is not None and stale_feature_age_sec >= self.min_feature_quality_sec:
            return self._blocked(strategy, state, regime, policy, execution_quality, "stale_feature", extra)
        if execution_quality.blocked:
            return self._blocked(strategy, state, regime, policy, execution_quality, execution_quality.blocked_reason, extra)
        if strategy in policy.blocked_strategies:
            return self._blocked(strategy, state, regime, policy, execution_quality, "strategy_blocked_by_regime", extra)
        if strategy == "opening_momentum" and market_phase != "OPENING_MOMENTUM":
            return self._blocked(strategy, state, regime, policy, execution_quality, "strategy_window_closed", extra)
        if strategy == "momentum_continuation":
            if regime.regime not in {RuntimeRegime.TRENDING}:
                return self._blocked(strategy, state, regime, policy, execution_quality, "momentum_requires_trending_regime", extra)
            fake_ratio = float((metrics or {}).get("fake_breakout_ratio") or 0.0)
            if fake_ratio and fake_ratio > 0.55:
                return self._blocked(strategy, state, regime, policy, execution_quality, "fake_breakout_ratio_high", extra)
        allowed_strategies = set(policy.live_strategies) | set(policy.small_live_strategies)
        if strategy not in allowed_strategies:
            return self._blocked(strategy, state, regime, policy, execution_quality, "strategy_not_allowed_by_regime", extra, permission="shadow_only")
        permission = "normal_live" if state == "normal_live" and strategy in policy.live_strategies else "small_live"
        return RuntimePermissionDecision(
            strategy=strategy,
            promotion_state=state,
            regime=regime.regime.value,
            runtime_permission=permission,
            allowed=True,
            allowed_size_ratio=policy.position_size_ratio,
            max_daily_trades=policy.max_daily_trades,
            max_trades_per_strategy=policy.max_trades_per_strategy,
            take_profit_pct=policy.take_profit_pct,
            stop_loss_pct=policy.stop_loss_pct,
            time_stop_sec=policy.time_stop_sec,
            hard_shift_triggered=regime.hard_shift_triggered,
            execution_quality_score=execution_quality.score,
            extra=extra,
        )

    @staticmethod
    def _blocked(
        strategy: str,
        state: str,
        regime: RegimeSnapshot,
        policy: RegimePolicy,
        execution_quality: ExecutionQualitySnapshot,
        reason: str,
        extra: dict[str, Any],
        *,
        permission: str = "blocked",
    ) -> RuntimePermissionDecision:
        return RuntimePermissionDecision(
            strategy=strategy,
            promotion_state=state,
            regime=regime.regime.value,
            runtime_permission=permission,
            allowed=False,
            blocked_reason=reason,
            allowed_size_ratio=0.0,
            max_daily_trades=policy.max_daily_trades,
            max_trades_per_strategy=policy.max_trades_per_strategy,
            take_profit_pct=policy.take_profit_pct,
            stop_loss_pct=policy.stop_loss_pct,
            time_stop_sec=policy.time_stop_sec,
            hard_shift_triggered=regime.hard_shift_triggered,
            execution_quality_score=execution_quality.score,
            extra=extra,
        )
