from __future__ import annotations

from src.trading.scalping.expected_edge import EdgeQuality, ExpectedEdgeInputs, ExpectedEdgeModel


def test_expected_net_edge_non_positive_blocks() -> None:
    model = ExpectedEdgeModel()
    decision = model.evaluate(
        ExpectedEdgeInputs(
            strategy_name="leader_only_shallow_pullback",
            spread_pct=0.020,
            expected_slippage_pct=0.010,
            orderbook_age_sec=4.0,
            fill_probability=0.2,
        )
    )

    assert decision.allowed is False
    assert decision.reject_reason in {
        "expected_net_edge_non_positive",
        "expected_mfe_below_cost_floor",
        "expected_mae_too_large",
    }


def test_risk_reward_below_min_degrades_to_shadow() -> None:
    model = ExpectedEdgeModel()
    decision = model.evaluate(
        ExpectedEdgeInputs(
            strategy_name="momentum_continuation",
            regime_score=70,
            current_regime="strong",
            historical_strategy_mfe_avg=0.010,
            historical_strategy_mae_avg=-0.008,
            spread_pct=0.0005,
            expected_slippage_pct=0.0002,
            orderbook_age_sec=0.2,
            depth_levels_available=5,
            microprice_edge=0.0005,
            orderbook_pressure=0.60,
            fill_probability=1.0,
        )
    )

    assert decision.reject_reason == ""
    assert decision.degrade_to_shadow is True
    assert decision.warning_reason == "risk_reward_below_strategy_min"


def test_runner_allowed_only_in_strong_quality_tape() -> None:
    model = ExpectedEdgeModel()
    decision = model.evaluate(
        ExpectedEdgeInputs(
            strategy_name="momentum_continuation",
            regime_score=85,
            current_regime="trending",
            breakout_success_ratio=0.65,
            fake_breakout_ratio=0.20,
            leader_persistence_score=0.80,
            leader_score=85,
            rank=1,
            vwap_gap=0.003,
            microprice_edge=0.0004,
            orderbook_pressure=0.65,
            spread_pct=0.0008,
            expected_slippage_pct=0.0002,
            orderbook_age_sec=0.2,
            depth_levels_available=5,
            fill_probability=1.0,
            execution_quality_state="SAFE",
        )
    )

    assert decision.runner_allowed is True
    assert decision.suggested_exit_profile.name.value == "RUNNER"
    assert decision.edge_quality in {EdgeQuality.ACCEPTABLE, EdgeQuality.STRONG}


def test_runner_blocked_in_weak_regime() -> None:
    model = ExpectedEdgeModel()
    decision = model.evaluate(
        ExpectedEdgeInputs(
            strategy_name="momentum_continuation",
            regime_score=35,
            current_regime="weak",
            breakout_success_ratio=0.65,
            fake_breakout_ratio=0.20,
            leader_persistence_score=0.80,
            leader_score=85,
            rank=1,
            vwap_gap=0.003,
            microprice_edge=0.0004,
            orderbook_pressure=0.65,
            spread_pct=0.0008,
            expected_slippage_pct=0.0002,
            orderbook_age_sec=0.2,
            depth_levels_available=5,
            fill_probability=1.0,
            execution_quality_state="SAFE",
        )
    )

    assert decision.runner_allowed is False


def test_calibration_overestimation_degrades_size() -> None:
    model = ExpectedEdgeModel()
    decision = model.evaluate(
        ExpectedEdgeInputs(
            strategy_name="leader_only_shallow_pullback",
            regime_score=70,
            current_regime="strong",
            leader_score=80,
            rank=1,
            vwap_gap=0.002,
            microprice_edge=0.0003,
            orderbook_pressure=0.62,
            spread_pct=0.0008,
            expected_slippage_pct=0.0002,
            orderbook_age_sec=0.2,
            depth_levels_available=5,
            fill_probability=1.0,
            calibration_error=-0.006,
        )
    )

    assert decision.degrade_to_shadow is True
    assert decision.warning_reason == "expected_edge_overestimated"
