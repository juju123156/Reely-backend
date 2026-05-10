from src.trading.scalping.regime_runtime import (
    ExecutionQualityGate,
    ExecutionQualityInputs,
    RegimeInputs,
    RegimeScoreEngine,
    RuntimePermissionGate,
    RuntimeRegime,
)
from src.trading.scalping.strategy_promotion import PromotionState


def test_regime_score_detects_strong_tape():
    engine = RegimeScoreEngine()
    snap = engine.update(RegimeInputs(
        index_trend=0.7,
        top_leader_persistence=0.9,
        vwap_hold_ratio=0.8,
        follow_through_ratio=0.8,
        breakout_success_ratio=0.8,
        fake_breakout_ratio=0.1,
        spread_stability=0.9,
        execution_quality_score=0.9,
        orderbook_stability=0.8,
        liquidity_concentration=0.8,
    ))

    assert snap.score >= 60
    assert snap.regime in {RuntimeRegime.STRONG, RuntimeRegime.TRENDING}


def test_regime_score_hard_shift_on_fake_breakout_spike():
    engine = RegimeScoreEngine()
    snap = engine.update(RegimeInputs(
        breakout_success_ratio=0.2,
        fake_breakout_ratio=0.8,
        spread_stability=0.7,
        execution_quality_score=0.8,
    ))

    assert snap.hard_shift_triggered is True
    assert snap.regime == RuntimeRegime.CHOPPY
    assert snap.regime_shift_reason == "fake_breakout_spike"


def test_execution_quality_blocks_stale_ticks():
    gate = ExecutionQualityGate()
    snap = gate.score(ExecutionQualityInputs(stale_tick_ratio=0.9))

    assert snap.blocked is True
    assert snap.blocked_reason == "stale_tick_repeated"


def test_runtime_permission_never_bypasses_promotion_gate():
    regime = RegimeScoreEngine().update(RegimeInputs(
        top_leader_persistence=0.9,
        breakout_success_ratio=0.8,
        fake_breakout_ratio=0.1,
        execution_quality_score=0.9,
    ))
    execution = ExecutionQualityGate().score(ExecutionQualityInputs())
    decision = RuntimePermissionGate().evaluate(
        strategy="vwap_reclaim",
        promotion_state=PromotionState.SHADOW_ONLY,
        regime=regime,
        execution_quality=execution,
        market_phase="MIDDAY_VWAP",
    )

    assert decision.allowed is False
    assert decision.runtime_permission == "shadow_only"
    assert decision.blocked_reason == "promotion_gate_shadow_only"


def test_runtime_permission_blocks_vwap_in_choppy_regime():
    regime = RegimeScoreEngine().update(RegimeInputs(
        breakout_success_ratio=0.3,
        fake_breakout_ratio=0.65,
        execution_quality_score=0.8,
    ))
    execution = ExecutionQualityGate().score(ExecutionQualityInputs())
    decision = RuntimePermissionGate().evaluate(
        strategy="vwap_reclaim",
        promotion_state=PromotionState.SMALL_LIVE,
        regime=regime,
        execution_quality=execution,
        market_phase="MIDDAY_VWAP",
    )

    assert decision.allowed is False
    assert decision.blocked_reason in {"hard_regime_shift", "strategy_blocked_by_regime"}


def test_runtime_permission_allows_leader_only_with_regime_size():
    regime = RegimeScoreEngine().update(RegimeInputs(
        index_trend=0.7,
        top_leader_persistence=0.9,
        breakout_success_ratio=0.8,
        fake_breakout_ratio=0.1,
        spread_stability=0.9,
        execution_quality_score=0.9,
    ))
    execution = ExecutionQualityGate().score(ExecutionQualityInputs())
    decision = RuntimePermissionGate().evaluate(
        strategy="leader_only_shallow_pullback",
        promotion_state=PromotionState.SMALL_LIVE,
        regime=regime,
        execution_quality=execution,
        market_phase="MORNING_SCALP",
        last_tick_age_sec=1.0,
        stale_feature_age_sec=1.0,
    )

    assert decision.allowed is True
    assert decision.allowed_size_ratio in {0.10, 0.15, 0.20}
    assert decision.max_daily_trades in {1, 2, 3}
