from __future__ import annotations

from datetime import datetime

from src.trading.scalping.events import TickEvent

from .fake_orderbook import FakeOrderbook


def make_tick(
    *,
    symbol: str = "TEST001",
    price: float = 10_000,
    book: FakeOrderbook | None = None,
    ts: datetime | None = None,
    buy_vol_total: float = 7_000,
    sell_vol_total: float = 3_000,
) -> TickEvent:
    book = book or FakeOrderbook(bid1=price - 10, ask1=price + 10)
    return TickEvent(
        symbol=symbol,
        price=price,
        buy_vol_total=buy_vol_total,
        sell_vol_total=sell_vol_total,
        tick_vol=100,
        acml_vol=100_000,
        acml_tr_pbmn=price * 100_000,
        time_str=(ts or datetime.now()).strftime("%H%M%S"),
        ts=ts or datetime.now(),
        **book.depth_fields(),
    )

