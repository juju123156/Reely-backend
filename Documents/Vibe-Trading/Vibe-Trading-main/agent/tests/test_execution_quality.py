from __future__ import annotations

from src.trading.scalping.execution_quality import ExecutionQualityRecord, VenueExecutionAnalyzer, VenueSlippageModel
from src.trading.scalping.venue import ExecutionVenue, VenuePolicy


def test_venue_execution_analyzer_counts_sor_failures_and_unknown_venue():
    analyzer = VenueExecutionAnalyzer()
    analyzer.record(ExecutionQualityRecord(
        order_id="1",
        symbol="005930",
        preferred_venue=ExecutionVenue.SOR,
        actual_venue=ExecutionVenue.UNKNOWN,
        venue_policy=VenuePolicy.SOR_BEST_EXECUTION,
        expected_price=70_000,
        fill_price=70_100,
        slippage_pct=0.0014,
        routing_result="fallback_krx",
    ))

    assert analyzer.sor_failure_count() == 1
    assert analyzer.unknown_venue_count() == 1


def test_venue_slippage_model_penalizes_nxt_more_than_krx():
    model = VenueSlippageModel()

    assert model.expected_slippage_bps(venue=ExecutionVenue.NXT, spread_bps=20) > model.expected_slippage_bps(
        venue=ExecutionVenue.KRX,
        spread_bps=20,
    )

