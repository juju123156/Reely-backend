from __future__ import annotations

from datetime import datetime, timedelta

from src.trading.scalping.microstructure_engine import TradePrint
from src.trading.scalping.opening_candle_engine import OpeningCandleEngine
from src.trading.scalping.venue import ExecutionVenue


def test_opening_candle_detects_gap_dump_and_first_low_break():
    engine = OpeningCandleEngine()
    start = datetime(2026, 5, 8, 9, 0, 0)
    prints = [
        (0, 103_000, 1_000, "buy"),
        (20, 102_000, 3_000, "sell"),
        (45, 101_000, 4_000, "sell"),
        (80, 100_500, 2_000, "sell"),
    ]
    for sec, price, qty, side in prints:
        engine.on_trade(TradePrint("005930", ExecutionVenue.KRX, price, qty, side, start + timedelta(seconds=sec)))

    snap = engine.snapshot(
        "005930",
        now=start + timedelta(minutes=2),
        opening_price=103_000,
        previous_close=98_000,
        current_price=100_000,
    )

    assert snap.data_quality == "partial"
    assert snap.first_1m_low_break is True
    assert snap.gap_dump_pattern is True
    assert snap.opening_sell_pressure > 0.5


def test_opening_candle_detects_three_minute_high_break_and_vwap_hold():
    engine = OpeningCandleEngine()
    start = datetime(2026, 5, 8, 9, 0, 0)
    for sec, price, qty, side in [
        (10, 100_000, 1_000, "buy"),
        (70, 101_000, 1_200, "buy"),
        (150, 101_500, 1_000, "buy"),
        (210, 102_500, 1_500, "buy"),
    ]:
        engine.on_trade(TradePrint("005930", ExecutionVenue.KRX, price, qty, side, start + timedelta(seconds=sec)))

    snap = engine.snapshot(
        "005930",
        now=start + timedelta(minutes=4),
        opening_price=100_000,
        previous_close=99_000,
        current_price=102_600,
    )

    assert snap.first_3m_high_break is True
    assert snap.vwap_hold is True
    assert snap.cumulative_bid_delta > 0

