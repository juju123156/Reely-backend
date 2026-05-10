"""Realtime KRX/NXT quote and trade microstructure metrics."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .venue import ExecutionVenue


@dataclass(frozen=True)
class QuoteEvent:
    symbol: str
    venue: ExecutionVenue
    bid1: float
    ask1: float
    bid_size1: float
    ask_size1: float
    ts: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class TradePrint:
    symbol: str
    venue: ExecutionVenue
    price: float
    qty: int
    side: str = "unknown"  # buy | sell | unknown
    ts: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class MicrostructureSnapshot:
    symbol: str
    venue: ExecutionVenue
    quote_lifetime_ms: float = 0.0
    cancel_rate_3s: float = 0.0
    cancel_rate_10s: float = 0.0
    bid_wall_persistence: float = 0.0
    displayed_bid_size: float = 0.0
    actual_executed_buy_volume: float = 0.0
    fake_bid_ratio: float = 0.0
    fake_bid_risk: float = 0.0
    spread_bps: float = 0.0
    data_quality: str = "missing"  # full | partial | missing
    reason_codes: list[str] = field(default_factory=list)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class RealtimeMicrostructureEngine:
    def __init__(self, *, max_age_sec: float = 30.0) -> None:
        self._quotes: dict[tuple[str, ExecutionVenue], deque[QuoteEvent]] = defaultdict(lambda: deque(maxlen=500))
        self._trades: dict[tuple[str, ExecutionVenue], deque[TradePrint]] = defaultdict(lambda: deque(maxlen=2000))
        self._max_age_sec = max_age_sec

    def on_quote(self, event: QuoteEvent) -> None:
        self._quotes[(event.symbol, event.venue)].append(event)

    def on_trade(self, event: TradePrint) -> None:
        self._trades[(event.symbol, event.venue)].append(event)

    def snapshot(self, symbol: str, venue: ExecutionVenue, *, now: datetime | None = None) -> MicrostructureSnapshot:
        now = now or datetime.now()
        key = (symbol, venue)
        quotes = self._recent_quotes(key, now)
        trades = self._recent_trades(key, now)
        if not quotes:
            return MicrostructureSnapshot(symbol=symbol, venue=venue, reason_codes=["quote_missing"])

        latest = quotes[-1]
        displayed_bid = sum(max(0.0, q.bid_size1) for q in quotes)
        executed_buy = sum(t.qty for t in trades if t.side == "buy")
        quote_lifetime_ms = self._avg_quote_lifetime_ms(quotes)
        cancel_3s = self._cancel_rate(quotes, now, 3.0)
        cancel_10s = self._cancel_rate(quotes, now, 10.0)
        persistence = self._bid_wall_persistence(quotes)
        fake_bid_ratio = displayed_bid / max(float(executed_buy), 1.0) if displayed_bid > 0 else 0.0
        spread_bps = ((latest.ask1 - latest.bid1) / latest.bid1 * 10000.0) if latest.bid1 > 0 and latest.ask1 > 0 else 0.0
        fake_bid_risk = _clamp(
            35.0 * cancel_3s
            + 25.0 * cancel_10s
            + 25.0 * (1.0 - persistence)
            + 15.0 * _clamp(fake_bid_ratio / 20.0, 0.0, 1.0)
        )
        reason_codes: list[str] = []
        if fake_bid_risk >= 70:
            reason_codes.append("fake_bid_risk_high")
        elif fake_bid_risk >= 50:
            reason_codes.append("fake_bid_risk_medium")
        if executed_buy <= 0:
            reason_codes.append("no_executed_buy_volume")
        quality = "full" if trades else "partial"
        return MicrostructureSnapshot(
            symbol=symbol,
            venue=venue,
            quote_lifetime_ms=quote_lifetime_ms,
            cancel_rate_3s=cancel_3s,
            cancel_rate_10s=cancel_10s,
            bid_wall_persistence=persistence,
            displayed_bid_size=displayed_bid,
            actual_executed_buy_volume=float(executed_buy),
            fake_bid_ratio=fake_bid_ratio,
            fake_bid_risk=fake_bid_risk,
            spread_bps=spread_bps,
            data_quality=quality,
            reason_codes=reason_codes,
        )

    def _recent_quotes(self, key: tuple[str, ExecutionVenue], now: datetime) -> list[QuoteEvent]:
        cutoff = now - timedelta(seconds=self._max_age_sec)
        return [q for q in self._quotes.get(key, []) if q.ts >= cutoff]

    def _recent_trades(self, key: tuple[str, ExecutionVenue], now: datetime) -> list[TradePrint]:
        cutoff = now - timedelta(seconds=self._max_age_sec)
        return [t for t in self._trades.get(key, []) if t.ts >= cutoff]

    @staticmethod
    def _avg_quote_lifetime_ms(quotes: list[QuoteEvent]) -> float:
        if len(quotes) < 2:
            return 0.0
        deltas = [
            (quotes[i].ts - quotes[i - 1].ts).total_seconds() * 1000.0
            for i in range(1, len(quotes))
        ]
        return sum(deltas) / len(deltas)

    @staticmethod
    def _cancel_rate(quotes: list[QuoteEvent], now: datetime, seconds: float) -> float:
        window = [q for q in quotes if q.ts >= now - timedelta(seconds=seconds)]
        if len(window) < 2:
            return 0.0
        total_displayed = sum(max(0.0, q.bid_size1) for q in window)
        canceled = 0.0
        for prev, cur in zip(window, window[1:]):
            if cur.bid_size1 < prev.bid_size1:
                canceled += prev.bid_size1 - cur.bid_size1
        return canceled / total_displayed if total_displayed > 0 else 0.0

    @staticmethod
    def _bid_wall_persistence(quotes: list[QuoteEvent]) -> float:
        if not quotes:
            return 0.0
        max_bid = max(q.bid_size1 for q in quotes)
        if max_bid <= 0:
            return 0.0
        wall_threshold = max_bid * 0.7
        wall_count = sum(1 for q in quotes if q.bid_size1 >= wall_threshold)
        return wall_count / len(quotes)
