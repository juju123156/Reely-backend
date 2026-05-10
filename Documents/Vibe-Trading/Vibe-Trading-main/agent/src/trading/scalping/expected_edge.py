"""Expected edge model for risk/reward, sizing and exit-profile decisions.

This model is intentionally not a signal generator and must not be used as a
"2~3% profit prediction" hard buy condition.  It is evaluated after a strategy
signal exists and before risk/order execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .constants import COMMISSION_RATE, EXPECTED_ENTRY_SLIPPAGE_PCT, EXPECTED_EXIT_SLIPPAGE_PCT, TAX_RATE_KOSDAQ
from .edge_profiles import EXIT_PROFILES, ExitProfile, ExitProfileName, StrategyEdgeProfile, profile_for


class EdgeQuality(str, Enum):
    NEGATIVE = "NEGATIVE"
    WEAK = "WEAK"
    ACCEPTABLE = "ACCEPTABLE"
    STRONG = "STRONG"


@dataclass(frozen=True)
class ExpectedEdgeInputs:
    strategy_name: str
    regime_score: float = 50.0
    current_regime: str = "normal"
    breakout_success_ratio: float = 0.5
    fake_breakout_ratio: float = 0.5
    leader_persistence_score: float = 0.5
    market_liquidity_state: str = "normal"
    strategy_promotion_state: str = "shadow_only"
    historical_strategy_mfe_avg: float = 0.0
    historical_strategy_mae_avg: float = 0.0
    strategy_hit_rate: float = 0.0
    strategy_net_expectancy: float = 0.0
    leader_score: float = 0.0
    rank: int = 999
    trade_value_rank: int = 999
    vwap_gap: float = 0.0
    vwap_hold_time: float = 0.0
    high_break_count: int = 0
    pullback_depth: float = 0.0
    recovery_strength: float = 0.0
    spread_pct: float = 0.0
    expected_slippage_pct: float = EXPECTED_ENTRY_SLIPPAGE_PCT + EXPECTED_EXIT_SLIPPAGE_PCT
    fee_pct: float = COMMISSION_RATE * 2.0
    tax_pct: float = TAX_RATE_KOSDAQ
    orderbook_age_sec: float = 999.0
    depth_levels_available: int = 1
    microprice_edge: float = 0.0
    orderbook_pressure: float = 0.5
    fill_probability: float = 1.0
    timeout_penalty: float = 0.0
    partial_fill_penalty: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    strategy_cooldown_state: str = ""
    max_daily_trades_remaining: int = 0
    current_position_count: int = 0
    calibration_error: float = 0.0
    execution_quality_state: str = "SAFE"


@dataclass(frozen=True)
class ExpectedEdgeDecision:
    strategy_name: str
    expected_mfe_pct: float
    expected_mae_pct: float
    expected_gross_edge_pct: float
    expected_cost_pct: float
    expected_net_edge_pct: float
    edge_quality: EdgeQuality
    risk_reward_ratio: float
    min_required_mfe_pct: float
    runner_allowed: bool
    suggested_position_multiplier: float
    suggested_exit_profile: ExitProfile
    reject_reason: str = ""
    warning_reason: str = ""
    degrade_to_shadow: bool = False
    components: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return not self.reject_reason and not self.degrade_to_shadow

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["edge_quality"] = self.edge_quality.value
        row["suggested_exit_profile"] = asdict(self.suggested_exit_profile)
        row["allowed"] = self.allowed
        return row


class ExpectedEdgeModel:
    def __init__(self, profiles: dict[str, StrategyEdgeProfile] | None = None) -> None:
        self._profiles = profiles or {}

    def evaluate(self, inputs: ExpectedEdgeInputs) -> ExpectedEdgeDecision:
        profile = self._profiles.get(inputs.strategy_name) or profile_for(inputs.strategy_name)
        expected_mfe = self._expected_mfe(inputs, profile)
        expected_mae = self._expected_mae(inputs, profile)
        cost = self._expected_cost(inputs)
        mae_risk = abs(expected_mae) * 0.35
        gross = expected_mfe - mae_risk
        net = gross - cost
        rr = expected_mfe / abs(expected_mae) if expected_mae < 0 else 0.0
        min_required = max(cost * 2.0, abs(expected_mae) * profile.min_risk_reward_ratio)
        runner = self._runner_allowed(inputs, profile)
        quality = self._quality(net, rr, profile)
        reject_reason = ""
        warning_reason = ""
        degrade = False

        if net <= 0:
            reject_reason = "expected_net_edge_non_positive"
        elif expected_mfe < cost * 2.0:
            reject_reason = "expected_mfe_below_cost_floor"
        elif expected_mae < profile.max_acceptable_mae_pct:
            reject_reason = "expected_mae_too_large"
        elif quality == EdgeQuality.NEGATIVE:
            reject_reason = "expected_edge_negative"
        elif rr < profile.min_risk_reward_ratio:
            degrade = True
            warning_reason = "risk_reward_below_strategy_min"
        elif quality == EdgeQuality.WEAK:
            degrade = True
            warning_reason = "expected_edge_weak"
        elif inputs.calibration_error < -0.004:
            degrade = True
            warning_reason = "expected_edge_overestimated"
        elif inputs.execution_quality_state.upper() == "CAUTION":
            degrade = True
            warning_reason = "execution_quality_caution"

        exit_profile = self._exit_profile(profile, runner, quality)
        return ExpectedEdgeDecision(
            strategy_name=inputs.strategy_name,
            expected_mfe_pct=round(expected_mfe, 6),
            expected_mae_pct=round(expected_mae, 6),
            expected_gross_edge_pct=round(gross, 6),
            expected_cost_pct=round(cost, 6),
            expected_net_edge_pct=round(net, 6),
            edge_quality=quality,
            risk_reward_ratio=round(rr, 4),
            min_required_mfe_pct=round(min_required, 6),
            runner_allowed=runner,
            suggested_position_multiplier=self._position_multiplier(quality, net, inputs),
            suggested_exit_profile=exit_profile,
            reject_reason=reject_reason,
            warning_reason=warning_reason,
            degrade_to_shadow=degrade,
            components={
                "target_profile": profile.strategy,
                "regime_score": inputs.regime_score,
                "leader_score": inputs.leader_score,
                "rank": inputs.rank,
                "microprice_edge": inputs.microprice_edge,
                "orderbook_pressure": inputs.orderbook_pressure,
                "fill_probability": inputs.fill_probability,
                "calibration_error": inputs.calibration_error,
            },
        )

    @staticmethod
    def _expected_cost(inputs: ExpectedEdgeInputs) -> float:
        spread_cost = max(0.0, inputs.spread_pct) * 0.5
        timeout_penalty = max(0.0, inputs.timeout_penalty)
        if inputs.orderbook_age_sec > 1.0:
            timeout_penalty += min(0.002, (inputs.orderbook_age_sec - 1.0) * 0.0005)
        if inputs.fill_probability < 1.0:
            timeout_penalty += (1.0 - max(0.0, inputs.fill_probability)) * 0.001
        return (
            max(0.0, inputs.expected_slippage_pct)
            + spread_cost
            + max(0.0, inputs.fee_pct)
            + max(0.0, inputs.tax_pct)
            + timeout_penalty
            + max(0.0, inputs.partial_fill_penalty)
        )

    @staticmethod
    def _expected_mfe(inputs: ExpectedEdgeInputs, profile: StrategyEdgeProfile) -> float:
        base = inputs.historical_strategy_mfe_avg if inputs.historical_strategy_mfe_avg > 0 else profile.target_mfe_mid_pct
        regime_boost = (max(0.0, min(100.0, inputs.regime_score)) - 50.0) / 100.0 * 0.004
        leader_boost = max(0.0, min(1.0, inputs.leader_score / 100.0)) * 0.003
        rank_penalty = 0.0 if inputs.rank <= 2 else min(0.004, (inputs.rank - 2) * 0.001)
        vwap_boost = max(-0.002, min(0.003, inputs.vwap_gap * 0.5))
        micro_boost = max(-0.002, min(0.003, inputs.microprice_edge * 10.0))
        breakout_quality = max(-0.003, min(0.003, (inputs.breakout_success_ratio - inputs.fake_breakout_ratio) * 0.004))
        return max(0.001, base + regime_boost + leader_boost + vwap_boost + micro_boost + breakout_quality - rank_penalty)

    @staticmethod
    def _expected_mae(inputs: ExpectedEdgeInputs, profile: StrategyEdgeProfile) -> float:
        base = inputs.historical_strategy_mae_avg if inputs.historical_strategy_mae_avg < 0 else profile.max_acceptable_mae_pct
        risk_penalty = 0.0
        if inputs.fake_breakout_ratio > 0.55:
            risk_penalty += 0.002
        if inputs.orderbook_pressure < 0.5:
            risk_penalty += 0.0015
        if inputs.spread_pct > 0.0025:
            risk_penalty += 0.001
        if inputs.consecutive_losses > 0:
            risk_penalty += min(0.002, inputs.consecutive_losses * 0.001)
        return min(-0.001, base - risk_penalty)

    @staticmethod
    def _runner_allowed(inputs: ExpectedEdgeInputs, profile: StrategyEdgeProfile) -> bool:
        regime_ok = inputs.current_regime in {"strong", "trending"}
        leader_ok = inputs.leader_persistence_score >= 0.65 or inputs.leader_score >= 75.0
        tape_ok = inputs.vwap_gap >= 0 and inputs.microprice_edge > 0 and inputs.orderbook_pressure >= 0.55
        breakout_ok = inputs.fake_breakout_ratio <= 0.45 and inputs.breakout_success_ratio >= 0.50
        execution_ok = inputs.execution_quality_state.upper() == "SAFE" and inputs.spread_pct <= 0.003 and inputs.orderbook_age_sec <= 1.0
        strategy_ok = profile.runner_candidate and inputs.strategy_name in {
            "momentum_continuation",
            "leader_only_shallow_pullback",
            "shallow_pullback",
            "vwap_reclaim",
            "opening_momentum",
        }
        return bool(regime_ok and leader_ok and tape_ok and breakout_ok and execution_ok and strategy_ok)

    @staticmethod
    def _quality(net: float, rr: float, profile: StrategyEdgeProfile) -> EdgeQuality:
        if net <= 0:
            return EdgeQuality.NEGATIVE
        if rr < profile.min_risk_reward_ratio or net < 0.002:
            return EdgeQuality.WEAK
        if net >= 0.006:
            return EdgeQuality.STRONG
        return EdgeQuality.ACCEPTABLE

    @staticmethod
    def _position_multiplier(quality: EdgeQuality, net: float, inputs: ExpectedEdgeInputs) -> float:
        if quality == EdgeQuality.NEGATIVE:
            return 0.0
        if quality == EdgeQuality.WEAK:
            base = 0.5
        elif quality == EdgeQuality.ACCEPTABLE:
            base = 1.0
        else:
            base = 1.2
        if inputs.consecutive_losses > 0:
            base *= max(0.4, 1.0 - inputs.consecutive_losses * 0.2)
        if inputs.execution_quality_state.upper() == "CAUTION":
            base *= 0.5
        return round(max(0.0, min(1.2, base)), 4)

    @staticmethod
    def _exit_profile(profile: StrategyEdgeProfile, runner: bool, quality: EdgeQuality) -> ExitProfile:
        if runner and quality in {EdgeQuality.ACCEPTABLE, EdgeQuality.STRONG}:
            return EXIT_PROFILES[ExitProfileName.RUNNER]
        if quality == EdgeQuality.WEAK:
            return EXIT_PROFILES[ExitProfileName.FAST_SCALP]
        return EXIT_PROFILES[profile.default_exit_profile]

