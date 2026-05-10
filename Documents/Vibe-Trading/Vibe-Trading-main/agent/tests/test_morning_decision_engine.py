from __future__ import annotations

from src.trading.scalping.morning_decision_engine import (
    MorningAction,
    MorningDecisionInput,
    MorningPositionDecisionEngine,
)


def test_missing_data_positive_pnl_exits_defensively():
    decision = MorningPositionDecisionEngine().decide(
        MorningDecisionInput(symbol="005930", pnl_pct=0.02, data_quality="missing")
    )

    assert decision.action == MorningAction.OPEN_EXIT
    assert decision.exit_qty_ratio == 1.0
    assert "pnl_positive_defensive_exit" in decision.reason_codes


def test_missing_data_negative_pnl_waits_for_first_candle():
    decision = MorningPositionDecisionEngine().decide(
        MorningDecisionInput(symbol="005930", pnl_pct=-0.01, data_quality="missing")
    )

    assert decision.action == MorningAction.HOLD_TO_0910
    assert decision.exit_qty_ratio == 0.0
    assert "pnl_negative_wait_first_candle" in decision.reason_codes


def test_first_low_break_and_fake_bid_trigger_open_exit():
    decision = MorningPositionDecisionEngine().decide(
        MorningDecisionInput(
            symbol="005930",
            pnl_pct=0.01,
            macro_risk_score=40,
            fake_bid_risk=85,
            first_1m_low_break=True,
            vwap_hold=False,
            opening_sell_pressure=0.7,
            data_quality="full",
        )
    )

    assert decision.action in {MorningAction.PREOPEN_EXIT, MorningAction.OPEN_EXIT}
    assert decision.exit_qty_ratio == 1.0
    assert "first_1m_low_break" in decision.reason_codes


def test_strong_opening_pattern_extends_hold():
    decision = MorningPositionDecisionEngine().decide(
        MorningDecisionInput(
            symbol="005930",
            pnl_pct=0.03,
            close_bet_grade="a_hold_candidate",
            macro_risk_score=5,
            fake_bid_risk=5,
            first_1m_low_break=False,
            first_3m_high_break=True,
            vwap_hold=True,
            cumulative_bid_delta=180_000,
            opening_sell_pressure=0.35,
            data_quality="full",
        )
    )

    assert decision.action == MorningAction.HOLD_EXTENSION
    assert decision.exit_qty_ratio == 0.0

