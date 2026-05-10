from __future__ import annotations

from datetime import datetime, timedelta

from src.trading.scalping.microstructure_engine import (
    QuoteEvent,
    RealtimeMicrostructureEngine,
    TradePrint,
)
from src.trading.scalping.venue import ExecutionVenue


def test_fake_bid_risk_rises_when_bid_wall_cancels_without_buy_fills():
    engine = RealtimeMicrostructureEngine(max_age_sec=30)
    now = datetime(2026, 5, 8, 9, 0, 5)
    for i, size in enumerate([100_000, 80_000, 20_000, 5_000]):
        engine.on_quote(
            QuoteEvent(
                symbol="005930",
                venue=ExecutionVenue.NXT,
                bid1=70_000,
                ask1=70_100,
                bid_size1=size,
                ask_size1=15_000,
                ts=now - timedelta(seconds=3 - i),
            )
        )

    snap = engine.snapshot("005930", ExecutionVenue.NXT, now=now)

    assert snap.data_quality == "partial"
    assert snap.cancel_rate_3s > 0.4
    assert snap.fake_bid_risk >= 50
    assert "no_executed_buy_volume" in snap.reason_codes


def test_microstructure_full_quality_when_quote_and_trade_exist():
    engine = RealtimeMicrostructureEngine()
    now = datetime(2026, 5, 8, 9, 0, 1)
    engine.on_quote(QuoteEvent("005930", ExecutionVenue.KRX, 70_000, 70_100, 10_000, 8_000, now))
    engine.on_trade(TradePrint("005930", ExecutionVenue.KRX, 70_100, 2_000, "buy", now))

    snap = engine.snapshot("005930", ExecutionVenue.KRX, now=now)

    assert snap.data_quality == "full"
    assert snap.actual_executed_buy_volume == 2_000
    assert snap.spread_bps > 0

