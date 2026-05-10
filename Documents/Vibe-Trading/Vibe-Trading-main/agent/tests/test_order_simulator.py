from __future__ import annotations

from src.trading.scalping.events import OrderRequest, TickEvent
from src.trading.scalping.order_simulator import OrderFillSimulator


def _tick(**kwargs) -> TickEvent:
    defaults = dict(
        symbol="005930",
        price=10_000,
        buy_vol_total=5_000,
        sell_vol_total=4_000,
        bid_qty=1_000,
        ask_qty=800,
        tick_vol=100,
        acml_vol=10_000,
        acml_tr_pbmn=100_000_000,
        time_str="100000",
        bid1_price=9_990,
        ask1_price=10_010,
    )
    defaults.update(kwargs)
    return TickEvent(**defaults)


def test_simulator_uses_ask_for_buy_and_bid_for_sell():
    sim = OrderFillSimulator(entry_slippage_pct=0.0, exit_slippage_pct=0.0, min_fill_probability=0.0)
    buy = OrderRequest("005930", "buy", 100, 10_020, "limit", "entry")
    sell = OrderRequest("005930", "sell", 100, 9_980, "limit", "exit_tp1")

    buy_fill = sim.simulate_fill(buy, _tick())
    sell_fill = sim.simulate_fill(sell, _tick())

    assert buy_fill.filled_qty == 100
    assert buy_fill.actual_fill_price >= 10_010
    assert sell_fill.filled_qty == 100
    assert sell_fill.actual_fill_price <= 9_990
    assert buy_fill.spread_pct > 0


def test_simulator_times_out_when_limit_does_not_cross():
    sim = OrderFillSimulator()
    buy = OrderRequest("005930", "buy", 100, 10_000, "limit", "entry")

    fill = sim.simulate_fill(buy, _tick())

    assert fill.timeout is True
    assert fill.status == "timeout"
    assert fill.filled_qty == 0
    assert fill.reason == "not_crossable_timeout"


def test_simulator_marks_partial_fill_when_l1_quantity_is_short():
    sim = OrderFillSimulator(min_fill_probability=0.0)
    buy = OrderRequest("005930", "buy", 1_000, 10_020, "limit", "entry")

    fill = sim.simulate_fill(buy, _tick(ask_qty=300))

    assert fill.partial_fill is True
    assert fill.filled_qty == 300
    assert fill.remaining_qty == 700


def test_simulator_round_trip_deducts_costs_and_slippage():
    sim = OrderFillSimulator(entry_slippage_pct=0.001, exit_slippage_pct=0.001, min_fill_probability=0.0)
    entry_req = OrderRequest("005930", "buy", 100, 10_020, "limit", "entry")
    exit_req = OrderRequest("005930", "sell", 100, 10_080, "limit", "exit_tp1")

    rt = sim.simulate_round_trip(
        entry_req=entry_req,
        entry_tick=_tick(price=10_000, bid1_price=9_990, ask1_price=10_010),
        exit_req=exit_req,
        exit_tick=_tick(price=10_100, bid1_price=10_090, ask1_price=10_110),
    )

    assert rt.entry.filled_qty == 100
    assert rt.exit.filled_qty == 100
    assert rt.total_cost > 0
    assert rt.net_pnl < rt.gross_pnl
    assert rt.net_pnl_pct < rt.gross_pnl_pct
