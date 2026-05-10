"""Deterministic L1 order/fill simulator for shadow and rehearsal modes."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import COMMISSION_RATE, EXPECTED_ENTRY_SLIPPAGE_PCT, EXPECTED_EXIT_SLIPPAGE_PCT, TAX_RATE_KOSDAQ, TAX_RATE_KOSPI
from .events import OrderRequest, TickEvent
from .orderbook_pressure import DepthFillSimulator, snapshot_from_tick


@dataclass(frozen=True)
class SimulatedFill:
    symbol: str
    side: str
    requested_qty: int
    filled_qty: int
    remaining_qty: int
    expected_price: float
    actual_fill_price: float
    spread_pct: float
    slippage_pct: float
    timeout: bool
    partial_fill: bool
    fill_probability: float
    commission: float
    tax: float
    status: str
    reason: str
    filled_levels: int = 0
    cancel_replace_cost_pct: float = 0.0

    @property
    def notional(self) -> float:
        return self.actual_fill_price * self.filled_qty


@dataclass(frozen=True)
class SimulatedRoundTrip:
    entry: SimulatedFill
    exit: SimulatedFill
    gross_pnl: float
    gross_pnl_pct: float
    net_pnl: float
    net_pnl_pct: float
    total_cost: float
    timeout: bool
    partial_fill: bool


class OrderFillSimulator:
    """Simulates executable fills using best bid/ask, queue quantity, spread and slippage.

    This is intentionally deterministic. It is not a backtest engine; it is a
    conservative execution-quality layer for deciding whether shadow MFE is
    plausibly monetizable after costs.
    """

    def __init__(
        self,
        *,
        entry_slippage_pct: float = EXPECTED_ENTRY_SLIPPAGE_PCT,
        exit_slippage_pct: float = EXPECTED_EXIT_SLIPPAGE_PCT,
        min_fill_probability: float = 0.25,
    ) -> None:
        self._entry_slippage_pct = max(0.0, entry_slippage_pct)
        self._exit_slippage_pct = max(0.0, exit_slippage_pct)
        self._min_fill_probability = max(0.0, min(1.0, min_fill_probability))
        self._depth_simulator = DepthFillSimulator()

    def simulate_fill(self, req: OrderRequest, tick: TickEvent, *, timeout_sec: float | None = None) -> SimulatedFill:
        if req.qty <= 0 or tick.price <= 0:
            return self._empty(req, expected_price=0.0, reason="invalid_qty_or_price")

        snapshot = snapshot_from_tick(tick)
        depth_estimate = self._depth_simulator.simulate(
            snapshot,
            side=req.side,
            qty=req.qty,
            limit_price=req.price if req.order_type == "limit" else 0.0,
        )
        bid1 = tick.bid1_price if tick.bid1_price > 0 else tick.price
        ask1 = tick.ask1_price if tick.ask1_price > 0 else tick.price
        spread_pct = max(0.0, (ask1 - bid1) / tick.price) if ask1 >= bid1 else 0.0
        expected = ask1 if req.side == "buy" else bid1
        if req.price > 0:
            expected = req.price

        if not self._is_crossable(req, bid1, ask1):
            return self._empty(req, expected_price=expected, reason="not_crossable_timeout")
        if depth_estimate.filled_qty <= 0:
            return self._empty(req, expected_price=expected, reason=depth_estimate.reason)

        displayed_qty = tick.ask_qty if req.side == "buy" else tick.bid_qty
        if req.order_type == "market":
            displayed_qty *= 1.5
        if displayed_qty <= 0:
            return self._empty(req, expected_price=expected, reason="empty_l1_timeout")

        filled_qty = min(depth_estimate.filled_qty, max(0, int(displayed_qty)) if displayed_qty > 0 else depth_estimate.filled_qty)
        partial = filled_qty < req.qty
        fill_probability = self._fill_probability(req.qty, displayed_qty, spread_pct, timeout_sec)
        if fill_probability < self._min_fill_probability:
            return self._empty(req, expected_price=expected, reason="low_fill_probability_timeout")

        liquidity_impact = max(0.0, req.qty / max(displayed_qty, 1.0) - 1.0) * spread_pct
        base_slippage = self._entry_slippage_pct if req.side == "buy" else self._exit_slippage_pct
        slippage = base_slippage + spread_pct * 0.5 + liquidity_impact + depth_estimate.expected_slippage_pct
        actual = depth_estimate.average_fill_price
        if actual <= 0:
            actual = ask1 * (1.0 + slippage) if req.side == "buy" else bid1 * (1.0 - slippage)
        if req.order_type == "limit" and req.price > 0:
            if req.side == "buy":
                actual = min(actual, req.price)
            else:
                actual = max(actual, req.price)

        commission = actual * filled_qty * COMMISSION_RATE
        tax_rate = TAX_RATE_KOSPI if req.market == "KOSPI" else TAX_RATE_KOSDAQ
        tax = actual * filled_qty * tax_rate if req.side == "sell" else 0.0
        return SimulatedFill(
            symbol=req.symbol,
            side=req.side,
            requested_qty=req.qty,
            filled_qty=filled_qty,
            remaining_qty=max(0, req.qty - filled_qty),
            expected_price=expected,
            actual_fill_price=actual,
            spread_pct=spread_pct,
            slippage_pct=slippage,
            timeout=False,
            partial_fill=partial,
            fill_probability=fill_probability,
            commission=commission,
            tax=tax,
            status="partial" if partial else "filled",
            reason=depth_estimate.reason,
            filled_levels=depth_estimate.filled_levels,
            cancel_replace_cost_pct=depth_estimate.cancel_replace_cost_pct,
        )

    def simulate_round_trip(
        self,
        *,
        entry_req: OrderRequest,
        entry_tick: TickEvent,
        exit_req: OrderRequest,
        exit_tick: TickEvent,
    ) -> SimulatedRoundTrip:
        entry = self.simulate_fill(entry_req, entry_tick)
        exit_qty = min(entry.filled_qty, exit_req.qty)
        if exit_qty != exit_req.qty:
            from dataclasses import replace
            exit_req = replace(exit_req, qty=exit_qty)
        exit_fill = self.simulate_fill(exit_req, exit_tick)
        qty = min(entry.filled_qty, exit_fill.filled_qty)
        gross = (exit_fill.actual_fill_price - entry.actual_fill_price) * qty
        cost = entry.commission + exit_fill.commission + exit_fill.tax
        net = gross - cost
        basis = entry.actual_fill_price * qty if qty > 0 else 0.0
        return SimulatedRoundTrip(
            entry=entry,
            exit=exit_fill,
            gross_pnl=gross,
            gross_pnl_pct=(gross / basis) if basis > 0 else 0.0,
            net_pnl=net,
            net_pnl_pct=(net / basis) if basis > 0 else 0.0,
            total_cost=cost,
            timeout=entry.timeout or exit_fill.timeout,
            partial_fill=entry.partial_fill or exit_fill.partial_fill,
        )

    @staticmethod
    def _is_crossable(req: OrderRequest, bid1: float, ask1: float) -> bool:
        if req.order_type == "market" or req.price <= 0:
            return True
        if req.side == "buy":
            return req.price >= ask1
        return req.price <= bid1

    @staticmethod
    def _fill_probability(qty: int, displayed_qty: float, spread_pct: float, timeout_sec: float | None) -> float:
        queue_ratio = min(1.0, max(0.0, displayed_qty / max(qty, 1)))
        timeout_boost = min(0.2, max(0.0, (timeout_sec or 0.0) / 25.0))
        spread_penalty = min(0.5, max(0.0, spread_pct * 50.0))
        return max(0.0, min(1.0, queue_ratio + timeout_boost - spread_penalty))

    @staticmethod
    def _empty(req: OrderRequest, *, expected_price: float, reason: str) -> SimulatedFill:
        return SimulatedFill(
            symbol=req.symbol,
            side=req.side,
            requested_qty=req.qty,
            filled_qty=0,
            remaining_qty=max(0, req.qty),
            expected_price=expected_price,
            actual_fill_price=0.0,
            spread_pct=0.0,
            slippage_pct=0.0,
            timeout=True,
            partial_fill=False,
            fill_probability=0.0,
            commission=0.0,
            tax=0.0,
            status="timeout",
            reason=reason,
            filled_levels=0,
            cancel_replace_cost_pct=0.0,
        )
