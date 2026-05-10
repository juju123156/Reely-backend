"""Strategy-specific expected-edge target profiles.

Profiles are not buy signals.  They define risk/reward and exit-management
expectations used after a strategy signal already exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExitProfileName(str, Enum):
    FAST_SCALP = "FAST_SCALP"
    BALANCED = "BALANCED"
    RUNNER = "RUNNER"


@dataclass(frozen=True)
class ExitProfile:
    name: ExitProfileName
    first_take_profit_pct: float
    time_stop_sec: int
    trailing_stop_pct: float
    runner_take_profit_pct: float = 0.0
    runner_size_ratio: float = 0.0


@dataclass(frozen=True)
class StrategyEdgeProfile:
    strategy: str
    target_mfe_low_pct: float
    target_mfe_high_pct: float
    max_acceptable_mae_pct: float
    min_risk_reward_ratio: float
    first_take_profit_pct: float
    default_exit_profile: ExitProfileName
    runner_candidate: bool = False

    @property
    def target_mfe_mid_pct(self) -> float:
        return (self.target_mfe_low_pct + self.target_mfe_high_pct) / 2.0


EXIT_PROFILES: dict[ExitProfileName, ExitProfile] = {
    ExitProfileName.FAST_SCALP: ExitProfile(
        name=ExitProfileName.FAST_SCALP,
        first_take_profit_pct=0.008,
        time_stop_sec=180,
        trailing_stop_pct=-0.008,
    ),
    ExitProfileName.BALANCED: ExitProfile(
        name=ExitProfileName.BALANCED,
        first_take_profit_pct=0.010,
        time_stop_sec=300,
        trailing_stop_pct=-0.010,
    ),
    ExitProfileName.RUNNER: ExitProfile(
        name=ExitProfileName.RUNNER,
        first_take_profit_pct=0.010,
        time_stop_sec=300,
        trailing_stop_pct=-0.012,
        runner_take_profit_pct=0.025,
        runner_size_ratio=0.25,
    ),
}


DEFAULT_EDGE_PROFILES: dict[str, StrategyEdgeProfile] = {
    "leader_only_shallow_pullback": StrategyEdgeProfile(
        strategy="leader_only_shallow_pullback",
        target_mfe_low_pct=0.008,
        target_mfe_high_pct=0.012,
        max_acceptable_mae_pct=-0.006,
        min_risk_reward_ratio=1.5,
        first_take_profit_pct=0.008,
        default_exit_profile=ExitProfileName.FAST_SCALP,
        runner_candidate=True,
    ),
    "shallow_pullback": StrategyEdgeProfile(
        strategy="shallow_pullback",
        target_mfe_low_pct=0.008,
        target_mfe_high_pct=0.012,
        max_acceptable_mae_pct=-0.006,
        min_risk_reward_ratio=1.5,
        first_take_profit_pct=0.008,
        default_exit_profile=ExitProfileName.FAST_SCALP,
        runner_candidate=True,
    ),
    "vwap_reclaim": StrategyEdgeProfile(
        strategy="vwap_reclaim",
        target_mfe_low_pct=0.008,
        target_mfe_high_pct=0.018,
        max_acceptable_mae_pct=-0.006,
        min_risk_reward_ratio=1.5,
        first_take_profit_pct=0.008,
        default_exit_profile=ExitProfileName.BALANCED,
        runner_candidate=True,
    ),
    "momentum_continuation": StrategyEdgeProfile(
        strategy="momentum_continuation",
        target_mfe_low_pct=0.015,
        target_mfe_high_pct=0.030,
        max_acceptable_mae_pct=-0.008,
        min_risk_reward_ratio=2.0,
        first_take_profit_pct=0.010,
        default_exit_profile=ExitProfileName.RUNNER,
        runner_candidate=True,
    ),
    "opening_momentum": StrategyEdgeProfile(
        strategy="opening_momentum",
        target_mfe_low_pct=0.010,
        target_mfe_high_pct=0.025,
        max_acceptable_mae_pct=-0.008,
        min_risk_reward_ratio=2.0,
        first_take_profit_pct=0.010,
        default_exit_profile=ExitProfileName.BALANCED,
        runner_candidate=True,
    ),
}


def profile_for(strategy: str) -> StrategyEdgeProfile:
    return DEFAULT_EDGE_PROFILES.get(
        strategy,
        StrategyEdgeProfile(
            strategy=strategy,
            target_mfe_low_pct=0.006,
            target_mfe_high_pct=0.010,
            max_acceptable_mae_pct=-0.006,
            min_risk_reward_ratio=1.5,
            first_take_profit_pct=0.008,
            default_exit_profile=ExitProfileName.FAST_SCALP,
        ),
    )

