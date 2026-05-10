from __future__ import annotations

import pytest

from src.trading.scalping.overnight_engine import (
    ExhaustionTrapDetector,
    FakeLiquidityDetector,
    GapRiskModel,
    HoldExtensionEngine,
    MacroOvernightContext,
    MorningExitEngine,
    NXTResilienceAnalyzer,
    OvernightAction,
    OvernightEngine,
)
from src.trading.scalping.venue import MarketSession, NxtMarketContext


def _ctx(**overrides) -> NxtMarketContext:
    data = dict(
        symbol="005930",
        session=MarketSession.NXT_AFTER,
        nxt_price=71_400,
        krx_reference_price=70_000,
        nxt_turnover=8e9,
        krx_turnover=150e9,
        nxt_spread=0.001,
        nxt_bid_ask_imbalance=1.3,
        data_quality="ok",
    )
    data.update(overrides)
    return NxtMarketContext(**data)


def test_exhaustion_trap_detects_price_up_volume_down_spread_wide():
    decision = ExhaustionTrapDetector().score(_ctx(
        nxt_price=72_000,
        turnover_slope=-1.0,
        trade_count_slope=-1.0,
        price_momentum_10m=0.02,
        nxt_spread=0.012,
    ))
    assert decision.action == OvernightAction.PREOPEN_EXIT
    assert decision.score >= 70


def test_fake_liquidity_low_fill_high_cancel_is_untrusted():
    decision = FakeLiquidityDetector().score(_ctx(
        bid_wall_fill_ratio=0.05,
        bid_cancel_rate=0.80,
        quote_lifetime_ms=200,
        bid_refresh_quality=0.05,
    ))
    assert decision.action == OvernightAction.EXIT_AT_OPEN
    assert decision.components["liquidity_trust"] < 35


def test_macro_overnight_risk_blocks_entry_on_risk_off():
    decision = GapRiskModel().score(MacroOvernightContext(
        nasdaq_futures_pct=-0.025,
        sox_pct=-0.03,
        nvidia_pct=-0.04,
        adr_pct=-0.03,
        usdkrw_pct=0.015,
        vix_pct=0.15,
        global_risk_on_score=15,
    ))
    assert decision.action == OvernightAction.BLOCK_ENTRY
    assert decision.score >= 70


def test_overnight_engine_reduces_but_keeps_nxt_exhaustion_entry():
    decision = OvernightEngine().evaluate_entry(_ctx(
        nxt_price=72_000,
        turnover_slope=-1.0,
        trade_count_slope=-1.0,
        price_momentum_10m=0.02,
        nxt_spread=0.012,
        bid_cancel_rate=0.8,
        bid_wall_fill_ratio=0.05,
    ))
    assert decision.action == OvernightAction.ENTER_REDUCED
    assert decision.components["exhaustion_score"] >= 70
    assert decision.metadata["close_bet_grade"] == "c_exit_priority"


def test_thin_nxt_liquidity_with_price_resilience_is_positive():
    decision = OvernightEngine().evaluate_entry(_ctx(
        nxt_turnover=1e9,
        krx_turnover=200e9,
        nxt_price=70_200,
        time_above_krx_close_ratio=0.90,
        sell_shock_recovery_pct=0.80,
        spread_stability=0.85,
        bid_absorption_strength=0.70,
        price_hold_under_thin_liquidity=0.90,
    ))
    assert decision.action == OvernightAction.ENTER_NORMAL
    assert decision.metadata["close_bet_grade"] in {"a_hold_candidate", "b_keep_candidate"}
    assert decision.components["nxt_resilience_score"] >= 70


def test_nxt_resilience_missing_is_neutral_not_reject():
    decision = NXTResilienceAnalyzer().score(NxtMarketContext(
        symbol="005930",
        session=MarketSession.NXT_AFTER,
        data_quality="missing",
    ))
    assert decision.score == 45
    assert decision.metadata["observation_quality"] == "missing"


def test_morning_exit_preopen_when_nxt_pre_discount_and_sell_delta():
    decision = MorningExitEngine().decide(_ctx(
        session=MarketSession.NXT_PRE,
        nxt_price=68_500,
        opening_sell_delta=-200_000,
        opening_auction_imbalance=0.6,
        first_1m_return=-0.008,
        first_red_low_break=True,
    ))
    assert decision.action in {OvernightAction.PREOPEN_EXIT, OvernightAction.EXIT_AT_OPEN}
    assert decision.score >= 50


def test_hold_extension_requires_vwap_bid_delta_volume_and_breakout():
    decision = HoldExtensionEngine().decide(_ctx(
        session=MarketSession.NXT_PRE,
        first_1m_return=0.012,
        first_3m_vwap_gap=0.004,
        intraday_vwap_gap=0.003,
        cumulative_bid_delta=150_000,
        volume_continuity=0.9,
        five_min_high_breakout=True,
    ))
    assert decision.action == OvernightAction.HOLD_EXTENSION
    assert decision.score >= 75


def test_missing_data_defaults_to_open_exit_not_hold():
    decision = OvernightEngine().decide_morning(NxtMarketContext(
        symbol="005930",
        session=MarketSession.NXT_PRE,
        data_quality="missing",
        krx_reference_price=70_000,
    ))
    assert decision.action == OvernightAction.EXIT_AT_OPEN
    assert decision.reason == "default_open_exit"
