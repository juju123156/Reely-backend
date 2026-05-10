"""Orderbook pressure and depth-walk execution estimates."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Any


@dataclass(frozen=True)
class BookLevel:
    price: float
    qty: float


@dataclass(frozen=True)
class OrderbookSnapshot:
    symbol: str
    bid_levels: tuple[BookLevel, ...] = ()
    ask_levels: tuple[BookLevel, ...] = ()
    last_price: float = 0.0
    ts_age_sec: float | None = None
    buy_vol_total: float = 0.0
    sell_vol_total: float = 0.0

    @property
    def bid1(self) -> BookLevel | None:
        return self.bid_levels[0] if self.bid_levels else None

    @property
    def ask1(self) -> BookLevel | None:
        return self.ask_levels[0] if self.ask_levels else None


@dataclass(frozen=True)
class DepthFillEstimate:
    side: str
    requested_qty: int
    filled_qty: int
    remaining_qty: int
    average_fill_price: float
    filled_levels: int
    partial_fill: bool
    expected_slippage_pct: float
    cancel_replace_cost_pct: float
    status: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "requested_qty": self.requested_qty,
            "filled_qty": self.filled_qty,
            "remaining_qty": self.remaining_qty,
            "average_fill_price": self.average_fill_price,
            "filled_levels": self.filled_levels,
            "partial_fill": self.partial_fill,
            "expected_slippage_pct": self.expected_slippage_pct,
            "cancel_replace_cost_pct": self.cancel_replace_cost_pct,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OrderbookPressure:
    symbol: str
    bid_depth: float
    ask_depth: float
    weighted_book_pressure: float
    microprice: float
    midpoint: float
    microprice_vs_mid: float
    spread_pct: float
    aggressive_buy_ratio: float
    aggressive_sell_ratio: float
    stale_orderbook: bool
    blocked: bool
    block_reason: str = ""
    components: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "weighted_book_pressure": self.weighted_book_pressure,
            "microprice": self.microprice,
            "midpoint": self.midpoint,
            "microprice_vs_mid": self.microprice_vs_mid,
            "spread_pct": self.spread_pct,
            "aggressive_buy_ratio": self.aggressive_buy_ratio,
            "aggressive_sell_ratio": self.aggressive_sell_ratio,
            "stale_orderbook": self.stale_orderbook,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "components": self.components,
        }


class OrderbookPressureFilter:
    def __init__(
        self,
        *,
        depth_levels: int = 3,
        max_spread_pct: float = 0.003,
        min_ask_depth_qty: float = 1.0,
        min_weighted_pressure: float = 0.52,
        aggressive_sell_spike_ratio: float = 0.65,
        stale_orderbook_sec: float = 5.0,
    ) -> None:
        self.depth_levels = max(1, depth_levels)
        self.max_spread_pct = max_spread_pct
        self.min_ask_depth_qty = min_ask_depth_qty
        self.min_weighted_pressure = min_weighted_pressure
        self.aggressive_sell_spike_ratio = aggressive_sell_spike_ratio
        self.stale_orderbook_sec = stale_orderbook_sec

    def evaluate(self, snapshot: OrderbookSnapshot, *, required_qty: int = 1) -> OrderbookPressure:
        bid1 = snapshot.bid1
        ask1 = snapshot.ask1
        if not bid1 or not ask1 or bid1.price <= 0 or ask1.price <= 0 or ask1.price <= bid1.price:
            return self._blocked(snapshot, "orderbook_collapse")

        midpoint = (bid1.price + ask1.price) / 2.0
        spread_pct = (ask1.price - bid1.price) / midpoint if midpoint > 0 else 1.0
        bid_depth = self._weighted_depth(snapshot.bid_levels)
        ask_depth = self._weighted_depth(snapshot.ask_levels)
        total_depth = bid_depth + ask_depth
        pressure = bid_depth / total_depth if total_depth > 0 else 0.0
        microprice = ((ask1.price * bid1.qty) + (bid1.price * ask1.qty)) / (bid1.qty + ask1.qty) if (bid1.qty + ask1.qty) > 0 else midpoint
        microprice_vs_mid = (microprice - midpoint) / midpoint if midpoint > 0 else 0.0
        buy_total = snapshot.buy_vol_total
        sell_total = snapshot.sell_vol_total
        flow_total = buy_total + sell_total
        aggressive_buy_ratio = buy_total / flow_total if flow_total > 0 else 0.5
        aggressive_sell_ratio = sell_total / flow_total if flow_total > 0 else 0.5
        stale = snapshot.ts_age_sec is not None and snapshot.ts_age_sec >= self.stale_orderbook_sec

        reason = ""
        if stale:
            reason = "stale_orderbook"
        elif spread_pct > self.max_spread_pct:
            reason = "spread_too_wide"
        elif ask_depth < max(self.min_ask_depth_qty, float(required_qty) * 0.5):
            reason = "ask_depth_thin"
        elif total_depth <= 0:
            reason = "orderbook_collapse"
        elif microprice_vs_mid < 0:
            reason = "microprice_below_mid"
        elif pressure < self.min_weighted_pressure:
            reason = "orderbook_pressure_weak"
        elif aggressive_sell_ratio >= self.aggressive_sell_spike_ratio:
            reason = "aggressive_sell_spike"

        return OrderbookPressure(
            symbol=snapshot.symbol,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            weighted_book_pressure=pressure,
            microprice=microprice,
            midpoint=midpoint,
            microprice_vs_mid=microprice_vs_mid,
            spread_pct=spread_pct,
            aggressive_buy_ratio=aggressive_buy_ratio,
            aggressive_sell_ratio=aggressive_sell_ratio,
            stale_orderbook=stale,
            blocked=bool(reason),
            block_reason=reason,
            components={
                "bid1": bid1.price,
                "ask1": ask1.price,
                "bid1_qty": bid1.qty,
                "ask1_qty": ask1.qty,
            },
        )

    def _weighted_depth(self, levels: tuple[BookLevel, ...]) -> float:
        depth = 0.0
        for idx, level in enumerate(levels[: self.depth_levels], start=1):
            if level.qty > 0:
                depth += level.qty / idx
        return depth

    @staticmethod
    def _attr(snapshot: OrderbookSnapshot, name: str) -> float:
        return float(getattr(snapshot, name, 0.0) or 0.0)

    @staticmethod
    def _blocked(snapshot: OrderbookSnapshot, reason: str) -> OrderbookPressure:
        return OrderbookPressure(
            symbol=snapshot.symbol,
            bid_depth=0.0,
            ask_depth=0.0,
            weighted_book_pressure=0.0,
            microprice=0.0,
            midpoint=0.0,
            microprice_vs_mid=0.0,
            spread_pct=1.0,
            aggressive_buy_ratio=0.0,
            aggressive_sell_ratio=1.0,
            stale_orderbook=False,
            blocked=True,
            block_reason=reason,
        )


class DepthFillSimulator:
    def simulate(self, snapshot: OrderbookSnapshot, *, side: str, qty: int, limit_price: float = 0.0) -> DepthFillEstimate:
        levels = snapshot.ask_levels if side == "buy" else snapshot.bid_levels
        if qty <= 0:
            return self._empty(side, qty, "invalid_qty")
        if not levels:
            return self._empty(side, qty, "empty_depth")

        remaining = qty
        filled = 0
        cost = 0.0
        filled_levels = 0
        best_price = levels[0].price
        for level in levels:
            if level.price <= 0 or level.qty <= 0:
                continue
            if limit_price > 0:
                if side == "buy" and level.price > limit_price:
                    break
                if side == "sell" and level.price < limit_price:
                    break
            take = min(remaining, int(level.qty))
            if take <= 0:
                continue
            filled += take
            remaining -= take
            cost += take * level.price
            filled_levels += 1
            if remaining <= 0:
                break

        if filled <= 0:
            return self._empty(side, qty, "not_fillable_at_limit")
        avg = cost / filled
        if best_price > 0:
            slip = (avg - best_price) / best_price if side == "buy" else (best_price - avg) / best_price
        else:
            slip = 0.0
        return DepthFillEstimate(
            side=side,
            requested_qty=qty,
            filled_qty=filled,
            remaining_qty=remaining,
            average_fill_price=avg,
            filled_levels=filled_levels,
            partial_fill=remaining > 0,
            expected_slippage_pct=max(0.0, slip),
            cancel_replace_cost_pct=0.0005 if remaining > 0 else 0.0,
            status="partial" if remaining > 0 else "filled",
            reason="partial_depth" if remaining > 0 else "filled_depth",
        )

    @staticmethod
    def _empty(side: str, qty: int, reason: str) -> DepthFillEstimate:
        return DepthFillEstimate(
            side=side,
            requested_qty=max(0, qty),
            filled_qty=0,
            remaining_qty=max(0, qty),
            average_fill_price=0.0,
            filled_levels=0,
            partial_fill=False,
            expected_slippage_pct=0.0,
            cancel_replace_cost_pct=0.0,
            status="timeout",
            reason=reason,
        )


@dataclass(frozen=True)
class OrderbookStabilitySnapshot:
    symbol: str
    ofi: float
    ofi_ewma: float
    qi: float
    qi_ewma: float
    orderbook_flicker_rate: float
    quote_cancel_like_change: float
    bid_depth_change_rate: float
    ask_depth_change_rate: float
    microprice_edge: float
    print_quote_alignment: float
    observer_healthy: bool
    observer_missing_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ofi": round(self.ofi, 4),
            "ofi_ewma": round(self.ofi_ewma, 4),
            "qi": round(self.qi, 4),
            "qi_ewma": round(self.qi_ewma, 4),
            "orderbook_flicker_rate": round(self.orderbook_flicker_rate, 4),
            "quote_cancel_like_change": round(self.quote_cancel_like_change, 4),
            "bid_depth_change_rate": round(self.bid_depth_change_rate, 4),
            "ask_depth_change_rate": round(self.ask_depth_change_rate, 4),
            "microprice_edge": round(self.microprice_edge, 5),
            "print_quote_alignment": round(self.print_quote_alignment, 4),
            "observer_healthy": self.observer_healthy,
            "observer_missing_reason": self.observer_missing_reason,
        }


class OrderbookStabilityObserver:
    """Shadow metric observer for OFI/QI/flicker diagnostics."""

    def __init__(self, max_samples: int = 120, ewma_alpha: float = 0.25) -> None:
        self.max_samples = max(10, max_samples)
        self.ewma_alpha = max(0.01, min(1.0, ewma_alpha))
        self._last: dict[str, OrderbookSnapshot] = {}
        self._ofi_ewma: dict[str, float] = {}
        self._qi_ewma: dict[str, float] = {}
        self._flickers: dict[str, deque[int]] = {}

    def observe(self, snapshot: OrderbookSnapshot) -> OrderbookStabilitySnapshot:
        bid1 = snapshot.bid1
        ask1 = snapshot.ask1
        if not bid1 or not ask1:
            return self._missing(snapshot.symbol, "top_of_book_missing")
        prev = self._last.get(snapshot.symbol)
        bid_depth = sum(max(0.0, x.qty) for x in snapshot.bid_levels[:3])
        ask_depth = sum(max(0.0, x.qty) for x in snapshot.ask_levels[:3])
        total = bid_depth + ask_depth
        qi = (bid_depth - ask_depth) / total if total > 0 else 0.0
        ofi = 0.0
        bid_change_rate = 0.0
        ask_change_rate = 0.0
        flicker = 0
        if prev and prev.bid1 and prev.ask1:
            prev_bid_depth = sum(max(0.0, x.qty) for x in prev.bid_levels[:3])
            prev_ask_depth = sum(max(0.0, x.qty) for x in prev.ask_levels[:3])
            ofi = (bid_depth - prev_bid_depth) - (ask_depth - prev_ask_depth)
            denom = max(1.0, prev_bid_depth + prev_ask_depth)
            bid_change_rate = abs(bid_depth - prev_bid_depth) / denom
            ask_change_rate = abs(ask_depth - prev_ask_depth) / denom
            flicker = int(
                bid1.price != prev.bid1.price
                or ask1.price != prev.ask1.price
                or bid_change_rate > 0.5
                or ask_change_rate > 0.5
            )
        flickers = self._flickers.setdefault(snapshot.symbol, deque(maxlen=self.max_samples))
        flickers.append(flicker)
        ofi_ewma = self._ewma(self._ofi_ewma.get(snapshot.symbol, ofi), ofi)
        qi_ewma = self._ewma(self._qi_ewma.get(snapshot.symbol, qi), qi)
        self._ofi_ewma[snapshot.symbol] = ofi_ewma
        self._qi_ewma[snapshot.symbol] = qi_ewma
        self._last[snapshot.symbol] = snapshot
        midpoint = (bid1.price + ask1.price) / 2.0 if bid1.price > 0 and ask1.price > 0 else 0.0
        microprice = ((ask1.price * bid1.qty) + (bid1.price * ask1.qty)) / (bid1.qty + ask1.qty) if (bid1.qty + ask1.qty) > 0 else midpoint
        edge = (microprice - midpoint) / midpoint if midpoint > 0 else 0.0
        alignment = 0.0
        if snapshot.last_price > 0 and midpoint > 0:
            alignment = 1.0 if (snapshot.last_price >= midpoint and edge >= 0) or (snapshot.last_price <= midpoint and edge <= 0) else -1.0
        return OrderbookStabilitySnapshot(
            symbol=snapshot.symbol,
            ofi=ofi,
            ofi_ewma=ofi_ewma,
            qi=qi,
            qi_ewma=qi_ewma,
            orderbook_flicker_rate=sum(flickers) / len(flickers) if flickers else 0.0,
            quote_cancel_like_change=max(bid_change_rate, ask_change_rate),
            bid_depth_change_rate=bid_change_rate,
            ask_depth_change_rate=ask_change_rate,
            microprice_edge=edge,
            print_quote_alignment=alignment,
            observer_healthy=len(flickers) >= 2,
            observer_missing_reason="" if len(flickers) >= 2 else "warming_up",
        )

    def _ewma(self, prev: float, value: float) -> float:
        return prev * (1.0 - self.ewma_alpha) + value * self.ewma_alpha

    @staticmethod
    def _missing(symbol: str, reason: str) -> OrderbookStabilitySnapshot:
        return OrderbookStabilitySnapshot(
            symbol=symbol,
            ofi=0.0,
            ofi_ewma=0.0,
            qi=0.0,
            qi_ewma=0.0,
            orderbook_flicker_rate=0.0,
            quote_cancel_like_change=0.0,
            bid_depth_change_rate=0.0,
            ask_depth_change_rate=0.0,
            microprice_edge=0.0,
            print_quote_alignment=0.0,
            observer_healthy=False,
            observer_missing_reason=reason,
        )


def snapshot_from_tick(tick: Any, *, depth_levels: int = 3, tick_age_sec: float | None = None) -> OrderbookSnapshot:
    symbol = str(getattr(tick, "symbol", "") or "")
    if tick_age_sec is None:
        tick_age_sec = float(getattr(tick, "orderbook_age_sec", 0.0) or 0.0)
    bid_levels = _extract_levels(tick, "bid", depth_levels)
    ask_levels = _extract_levels(tick, "ask", depth_levels)
    if not bid_levels:
        bid_levels = (BookLevel(float(getattr(tick, "bid1_price", 0.0) or 0.0), float(getattr(tick, "bid_qty", 0.0) or 0.0)),)
    if not ask_levels:
        ask_levels = (BookLevel(float(getattr(tick, "ask1_price", 0.0) or 0.0), float(getattr(tick, "ask_qty", 0.0) or 0.0)),)
    return OrderbookSnapshot(
        symbol=symbol,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        last_price=float(getattr(tick, "price", 0.0) or 0.0),
        ts_age_sec=tick_age_sec,
        buy_vol_total=float(getattr(tick, "buy_vol_total", 0.0) or 0.0),
        sell_vol_total=float(getattr(tick, "sell_vol_total", 0.0) or 0.0),
    )


def _extract_levels(tick: Any, side: str, depth_levels: int) -> tuple[BookLevel, ...]:
    price_names = [f"{side}{i}_price" for i in range(1, depth_levels + 1)]
    levels: list[BookLevel] = []
    for idx, price_name in enumerate(price_names, start=1):
        price = float(getattr(tick, price_name, 0.0) or 0.0)
        qty = float(getattr(tick, f"{side}{idx}_qty", 0.0) or 0.0)
        if idx == 1 and qty <= 0:
            qty = float(getattr(tick, f"{side}_qty", 0.0) or 0.0)
        if price > 0 and qty > 0:
            levels.append(BookLevel(price, qty))
    return tuple(levels)
