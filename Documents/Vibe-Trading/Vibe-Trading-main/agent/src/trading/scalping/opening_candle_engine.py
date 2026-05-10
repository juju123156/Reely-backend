"""Build first 1m/3m/5m opening candles from realtime trade prints."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from .microstructure_engine import TradePrint


@dataclass(frozen=True)
class OpeningCandleSnapshot:
    symbol: str
    first_1m_open: float = 0.0
    first_1m_high: float = 0.0
    first_1m_low: float = 0.0
    first_1m_close: float = 0.0
    first_3m_high: float = 0.0
    first_3m_low: float = 0.0
    first_5m_high: float = 0.0
    vwap_1m: float = 0.0
    vwap_3m: float = 0.0
    vwap_5m: float = 0.0
    buy_volume: int = 0
    sell_volume: int = 0
    bid_delta: int = 0
    cumulative_bid_delta: int = 0
    first_1m_low_break: bool = False
    first_3m_high_break: bool = False
    vwap_hold: bool = False
    opening_sell_pressure: float = 0.0
    gap_dump_pattern: bool = False
    trading_value_drop_3m: bool = False
    data_quality: str = "missing"
    reason_codes: list[str] = field(default_factory=list)


class OpeningCandleEngine:
    def __init__(self, *, market_open: time = time(9, 0)) -> None:
        self._prints: dict[str, deque[TradePrint]] = defaultdict(lambda: deque(maxlen=5000))
        self._market_open = market_open

    def on_trade(self, print_: TradePrint) -> None:
        self._prints[print_.symbol].append(print_)

    def snapshot(
        self,
        symbol: str,
        *,
        now: datetime | None = None,
        opening_price: float = 0.0,
        previous_close: float = 0.0,
        current_price: float = 0.0,
    ) -> OpeningCandleSnapshot:
        now = now or datetime.now()
        start = now.replace(hour=self._market_open.hour, minute=self._market_open.minute, second=0, microsecond=0)
        prints = [p for p in self._prints.get(symbol, []) if start <= p.ts <= now]
        if not prints:
            return OpeningCandleSnapshot(symbol=symbol, reason_codes=["opening_trades_missing"])

        p1 = [p for p in prints if p.ts < start + timedelta(minutes=1)]
        p3 = [p for p in prints if p.ts < start + timedelta(minutes=3)]
        p5 = [p for p in prints if p.ts < start + timedelta(minutes=5)]
        first_1m = self._ohlcv(p1)
        first_3m = self._ohlcv(p3)
        first_5m = self._ohlcv(p5)
        current = current_price or prints[-1].price
        buy_volume = sum(p.qty for p in prints if p.side == "buy")
        sell_volume = sum(p.qty for p in prints if p.side == "sell")
        bid_delta = buy_volume - sell_volume
        opening_sell_pressure = sell_volume / max(buy_volume + sell_volume, 1)
        first_1m_low_break = bool(first_1m["low"] > 0 and current < first_1m["low"])
        first_3m_high_break = bool(first_3m["high"] > 0 and current > first_3m["high"] and now >= start + timedelta(minutes=3))
        vwap_ref = first_3m["vwap"] or first_1m["vwap"]
        vwap_hold = bool(vwap_ref > 0 and current >= vwap_ref)
        gap_pct = (opening_price - previous_close) / previous_close if previous_close > 0 and opening_price > 0 else 0.0
        first_1m_bearish = first_1m["close"] < first_1m["open"] if first_1m["open"] > 0 else False
        gap_dump = gap_pct > 0.03 and opening_sell_pressure > 0.58 and first_1m_bearish
        trading_value_drop_3m = self._trading_value_drop(p1, p3)
        reasons: list[str] = []
        if first_1m_low_break:
            reasons.append("first_1m_low_break")
        if first_3m_high_break and vwap_hold:
            reasons.append("first_3m_high_break")
        if gap_dump:
            reasons.append("gap_dump_pattern")
        if trading_value_drop_3m:
            reasons.append("trading_value_drop_3m")
        quality = "full" if now >= start + timedelta(minutes=5) else "partial"
        return OpeningCandleSnapshot(
            symbol=symbol,
            first_1m_open=first_1m["open"],
            first_1m_high=first_1m["high"],
            first_1m_low=first_1m["low"],
            first_1m_close=first_1m["close"],
            first_3m_high=first_3m["high"],
            first_3m_low=first_3m["low"],
            first_5m_high=first_5m["high"],
            vwap_1m=first_1m["vwap"],
            vwap_3m=first_3m["vwap"],
            vwap_5m=first_5m["vwap"],
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            bid_delta=bid_delta,
            cumulative_bid_delta=bid_delta,
            first_1m_low_break=first_1m_low_break,
            first_3m_high_break=first_3m_high_break,
            vwap_hold=vwap_hold,
            opening_sell_pressure=opening_sell_pressure,
            gap_dump_pattern=gap_dump,
            trading_value_drop_3m=trading_value_drop_3m,
            data_quality=quality,
            reason_codes=reasons,
        )

    @staticmethod
    def _ohlcv(prints: list[TradePrint]) -> dict[str, float]:
        if not prints:
            return {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "vwap": 0.0, "value": 0.0}
        value = sum(p.price * p.qty for p in prints)
        volume = sum(p.qty for p in prints)
        return {
            "open": prints[0].price,
            "high": max(p.price for p in prints),
            "low": min(p.price for p in prints),
            "close": prints[-1].price,
            "vwap": value / volume if volume > 0 else 0.0,
            "value": value,
        }

    @staticmethod
    def _trading_value_drop(p1: list[TradePrint], p3: list[TradePrint]) -> bool:
        if not p1 or len(p3) <= len(p1):
            return False
        v1 = sum(p.price * p.qty for p in p1)
        later = p3[len(p1):]
        v_later_per_min = sum(p.price * p.qty for p in later) / 2.0
        return v1 > 0 and v_later_per_min < v1 * 0.35
