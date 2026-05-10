"""AfterMarketEngine — 시간외 단일가 CLOSE_BET 추가매수."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .constants import (
    AFTER_MARKET_END_TIME,
    AFTER_MARKET_FILL_TIMEOUT,
    AFTER_MARKET_SCAN_INTERVAL_SEC,
    AFTER_MARKET_START_TIME,
    OVERNIGHT_MAX_TOTAL,
)
from .events import OrderRequest
from .position_type import PositionType
from .venue import ExecutionVenue, MarketSession, VenuePolicy

logger = logging.getLogger(__name__)


@dataclass
class AfterMarketCandidate:
    symbol: str
    name: str | None
    price: float
    bid_qty: int
    ask_qty: int
    bid_ask_ratio: float
    existing_close_bet_qty: int
    add_qty: int
    reason: str


class AfterMarketEngine:
    def __init__(
        self,
        *,
        adapter: Any,
        executor: Any,
        position_mgr: Any,
        risk_mgr: Any,
        store: Any = None,
        journal: Any = None,
        env: str = "demo",
        dry_run: bool = True,
    ) -> None:
        self._adapter = adapter
        self._executor = executor
        self._position_mgr = position_mgr
        self._risk_mgr = risk_mgr
        self._store = store
        self._journal = journal
        self._env = env
        self._dry_run = dry_run

    async def run(self):
        while AFTER_MARKET_START_TIME <= datetime.now().time() <= AFTER_MARKET_END_TIME:
            candidates = await self.scan_candidates()
            for c in candidates:
                await self.add_position(c.symbol, c.add_qty, c.price)
            await asyncio.sleep(AFTER_MARKET_SCAN_INTERVAL_SEC)

    async def scan_candidates(self) -> list[AfterMarketCandidate]:
        if not self._position_mgr:
            return []
        positions = {
            sym: pos
            for sym, pos in self._position_mgr.active_positions().items()
            if getattr(pos, "position_type", PositionType.UNKNOWN) == PositionType.CLOSE_BET
        }
        if not positions:
            return []

        candidates: list[AfterMarketCandidate] = []
        for symbol, pos in positions.items():
            ob = self._get_order_book(symbol)
            bid_qty = int(ob.get("bid_qty") or ob.get("total_bid_qty") or 0)
            ask_qty = int(ob.get("ask_qty") or ob.get("total_ask_qty") or 0)
            price = float(ob.get("price") or ob.get("bid_price") or pos.avg_price)
            ratio = bid_qty / ask_qty if ask_qty > 0 else 0.0
            if bid_qty <= 0 or ask_qty <= 0 or ratio < 1.2:
                logger.warning("AFTER_MARKET weak book: %s ratio=%.2f", symbol, ratio)
                continue
            add_qty = max(1, int(pos.remaining_qty * 0.2))
            if self._would_exceed_overnight_limit(price * add_qty):
                logger.info("AFTER_MARKET blocked exposure: %s", symbol)
                continue
            candidates.append(
                AfterMarketCandidate(
                    symbol=symbol,
                    name=None,
                    price=price,
                    bid_qty=bid_qty,
                    ask_qty=ask_qty,
                    bid_ask_ratio=ratio,
                    existing_close_bet_qty=pos.remaining_qty,
                    add_qty=add_qty,
                    reason="after_market_bid_support",
                )
            )
        return candidates

    async def add_position(self, symbol: str, qty: int, price: float):
        if qty <= 0 or price <= 0:
            return None
        if self._env == "demo" and not self._dry_run:
            raise RuntimeError("VTS/demo does not allow real after-market ORD_DVSN=07 orders")

        pos = self._position_mgr.get_position(symbol) if self._position_mgr else None
        if not pos or pos.position_type != PositionType.CLOSE_BET:
            logger.warning("AFTER_MARKET blocked non-CLOSE_BET symbol: %s", symbol)
            return None

        req = OrderRequest(
            symbol=symbol,
            side="buy",
            qty=qty,
            price=price,
            order_type="limit",
            reason="after_market_add",
            market=pos.market,
            position_type=PositionType.CLOSE_BET,
            order_session="after_market",
            ord_dvsn_override="07",
            listing_market=pos.listing_market,
            execution_venue=ExecutionVenue.NXT,
            preferred_venue=ExecutionVenue.NXT,
            actual_venue=ExecutionVenue.NXT if self._dry_run else ExecutionVenue.UNKNOWN,
            venue_policy=VenuePolicy.NXT_ONLY if self._dry_run else VenuePolicy.FALLBACK_KRX,
            market_session=MarketSession.NXT_AFTER,
        )
        order_no = await self._executor.submit(req)
        if not order_no:
            return None
        fill = await self._executor.wait_fill(order_no, timeout=AFTER_MARKET_FILL_TIMEOUT)
        if not fill:
            await self.handle_unfilled(order_no)
            return None

        self._position_mgr.on_fill_entry(
            fill,
            atr=pos.atr_at_entry,
            position_type=PositionType.CLOSE_BET,
            strategy_id="close_bet",
            entry_session=MarketSession.NXT_AFTER.value,
            intended_exit_session="next_open",
            listing_market=pos.listing_market,
            preferred_venue=ExecutionVenue.NXT,
            actual_venue=ExecutionVenue.NXT if self._dry_run else ExecutionVenue.UNKNOWN,
            venue_policy=VenuePolicy.NXT_ONLY if self._dry_run else VenuePolicy.FALLBACK_KRX,
            market_session=MarketSession.NXT_AFTER,
            nxt_reference_price=fill.fill_price,
        )
        if self._store:
            await self._store.save_position(symbol, {
                "symbol": symbol,
                "avg_price": pos.avg_price,
                "entry_price": pos.entry_price,
                "remaining_qty": pos.remaining_qty,
                "total_qty": pos.total_qty,
                "phase": pos.phase.value,
                "atr_at_entry": pos.atr_at_entry,
                "hard_stop": pos.hard_stop,
                "break_even_stop": pos.break_even_stop,
                "trailing_high": pos.trailing_high,
                "trailing_stop": pos.trailing_stop,
                "market": pos.market,
                "position_type": PositionType.CLOSE_BET.value,
                "opened_at": pos.opened_at.isoformat(),
                "strategy_id": "close_bet",
                "entry_session": MarketSession.NXT_AFTER.value,
                "intended_exit_session": "next_open",
                "listing_market": pos.listing_market.value,
                "execution_venue": ExecutionVenue.NXT.value,
                "preferred_venue": ExecutionVenue.NXT.value,
                "actual_venue": (ExecutionVenue.NXT if self._dry_run else ExecutionVenue.UNKNOWN).value,
                "venue_policy": (VenuePolicy.NXT_ONLY if self._dry_run else VenuePolicy.FALLBACK_KRX).value,
                "market_session": MarketSession.NXT_AFTER.value,
                "krx_entry_price": pos.krx_entry_price,
                "nxt_reference_price": fill.fill_price,
                "venue_price_gap_at_entry": pos.venue_price_gap_at_entry,
                "nxt_after_signal": pos.nxt_after_signal,
                "nxt_pre_signal": pos.nxt_pre_signal,
            })
        if self._store:
            await self._store.log_trade({
                "type": "entry",
                "symbol": symbol,
                "side": "buy",
                "reason": "after_market_add",
                "position_type": PositionType.CLOSE_BET.value,
                "qty": fill.filled_qty,
                "fill_price": fill.fill_price,
                "after_market_added": True,
                "after_market_add_qty": fill.filled_qty,
                "after_market_add_price": fill.fill_price,
                "after_market_order_status": "filled",
                "execution_venue": ExecutionVenue.NXT.value,
                "preferred_venue": ExecutionVenue.NXT.value,
                "actual_venue": (ExecutionVenue.NXT if self._dry_run else ExecutionVenue.UNKNOWN).value,
                "venue_policy": (VenuePolicy.NXT_ONLY if self._dry_run else VenuePolicy.FALLBACK_KRX).value,
                "market_session": MarketSession.NXT_AFTER.value,
            })
        return fill

    async def handle_unfilled(self, order_no: str):
        ok = await self._executor.cancel_pending(order_no)
        if not ok:
            logger.warning("AFTER_MARKET cancel failed: %s", order_no)
        if self._store:
            await self._store.log_trade({
                "type": "order_cancel",
                "reason": "after_market_unfilled_cancel",
                "order_no": order_no,
                "position_type": PositionType.CLOSE_BET.value,
                "after_market_order_status": "canceled" if ok else "cancel_failed",
            })
        return ok

    def _get_order_book(self, symbol: str) -> dict:
        try:
            result = self._adapter.get_order_book(symbol, env_dv=self._env)
            if result.get("status") == "ok":
                return result.get("order_book") or result
        except Exception as exc:
            logger.debug("AFTER_MARKET order book failed %s: %s", symbol, exc)
        return {}

    def _would_exceed_overnight_limit(self, add_amount: float) -> bool:
        if not self._risk_mgr or self._risk_mgr.state.capital <= 0:
            return True
        current = self._risk_mgr.exposure_by_position_type(
            self._position_mgr.active_positions(),
            PositionType.CLOSE_BET,
        )
        return (current + add_amount) / self._risk_mgr.state.capital > OVERNIGHT_MAX_TOTAL
