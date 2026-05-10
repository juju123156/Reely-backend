from __future__ import annotations

from datetime import datetime

from src.trading.scalping.events import OrderRequest, TickEvent
from src.trading.scalping.order_simulator import OrderFillSimulator
from src.trading.scalping.orderbook_pressure import (
    BookLevel,
    DepthFillSimulator,
    OrderbookPressureFilter,
    OrderbookSnapshot,
    OrderbookStabilityObserver,
)


def _snapshot() -> OrderbookSnapshot:
    return OrderbookSnapshot(
        symbol="005930",
        bid_levels=(BookLevel(10_000, 2_000), BookLevel(9_990, 1_000)),
        ask_levels=(BookLevel(10_010, 500), BookLevel(10_020, 500), BookLevel(10_030, 500)),
        last_price=10_000,
        ts_age_sec=0.2,
        buy_vol_total=700,
        sell_vol_total=300,
    )


def test_orderbook_pressure_allows_bid_dominant_book():
    pressure = OrderbookPressureFilter(max_spread_pct=0.003).evaluate(_snapshot(), required_qty=100)

    assert pressure.blocked is False
    assert pressure.weighted_book_pressure > 0.52
    assert pressure.microprice_vs_mid > 0
    assert pressure.aggressive_buy_ratio == 0.7


def test_orderbook_pressure_blocks_stale_book():
    snapshot = OrderbookSnapshot(
        symbol="005930",
        bid_levels=(BookLevel(10_000, 1_000),),
        ask_levels=(BookLevel(10_010, 1_000),),
        last_price=10_000,
        ts_age_sec=6.0,
    )

    pressure = OrderbookPressureFilter(stale_orderbook_sec=5.0).evaluate(snapshot, required_qty=100)

    assert pressure.blocked is True
    assert pressure.block_reason == "stale_orderbook"


def test_depth_fill_simulator_walks_book_and_marks_partial():
    estimate = DepthFillSimulator().simulate(
        _snapshot(),
        side="buy",
        qty=1_200,
        limit_price=10_030,
    )

    assert estimate.filled_qty == 1_200
    assert estimate.remaining_qty == 0
    assert estimate.filled_levels == 3
    assert estimate.average_fill_price > 10_010

    partial = DepthFillSimulator().simulate(
        _snapshot(),
        side="buy",
        qty=2_000,
        limit_price=10_030,
    )
    assert partial.partial_fill is True
    assert partial.remaining_qty == 500


def test_order_fill_simulator_uses_depth_fill_estimate():
    tick = TickEvent(
        symbol="005930",
        price=10_000,
        buy_vol_total=700,
        sell_vol_total=300,
        bid_qty=2_000,
        ask_qty=1_500,
        tick_vol=100,
        acml_vol=10_000,
        acml_tr_pbmn=100_000_000,
        time_str="100000",
        ask1_price=10_010,
        bid1_price=10_000,
        ts=datetime.now(),
    )
    req = OrderRequest("005930", "buy", 1_000, 10_010, "limit", "entry_1")

    fill = OrderFillSimulator().simulate_fill(req, tick, timeout_sec=2.0)

    assert fill.timeout is False
    assert fill.filled_qty == 1_000
    assert fill.actual_fill_price == 10_010
    assert fill.reason == "filled_depth"


def test_orderbook_stability_observer_tracks_ofi_qi_and_flicker():
    observer = OrderbookStabilityObserver(max_samples=10)
    first = OrderbookSnapshot(
        symbol="005930",
        bid_levels=(BookLevel(1000, 100), BookLevel(999, 80), BookLevel(998, 60)),
        ask_levels=(BookLevel(1001, 90), BookLevel(1002, 70), BookLevel(1003, 50)),
        last_price=1000,
    )
    second = OrderbookSnapshot(
        symbol="005930",
        bid_levels=(BookLevel(1000, 160), BookLevel(999, 100), BookLevel(998, 70)),
        ask_levels=(BookLevel(1001, 60), BookLevel(1002, 50), BookLevel(1003, 40)),
        last_price=1001,
    )

    observer.observe(first)
    snap = observer.observe(second)

    assert snap.observer_healthy is True
    assert snap.ofi > 0
    assert snap.qi > 0
    assert "ofi_ewma" in snap.to_dict()
