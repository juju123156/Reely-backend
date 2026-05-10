"""Tests for OrderExecutor, MarketScanner, StateStore."""

from __future__ import annotations

import asyncio
from datetime import time
from unittest.mock import MagicMock, patch

import pytest

from src.trading.scalping.order_executor import OrderExecutor
from src.trading.scalping.market_scanner import MarketScanner, SymbolCandidate
from src.trading.scalping.state_store import InMemoryStateStore, make_state_store
from src.trading.scalping.events import OrderRequest, FillEvent
from src.trading.scalping.venue import ExecutionVenue, VenuePolicy
from src.trading.scalping.constants import (
    MIN_TRADING_VALUE, MIN_PRICE, MIN_CHANGE_PCT, MAX_CHANGE_PCT,
)


# ─────────────────────────────────────────────────────────────────────────────
# OrderExecutor — dry_run 모드
# ─────────────────────────────────────────────────────────────────────────────

def _make_adapter():
    adapter = MagicMock()
    adapter.place_order_cash.return_value = {
        "status": "ok", "order_no": "001", "krx_org_no": "99999",
    }
    adapter.cancel_order.return_value = {"status": "ok"}
    adapter.inquire_psbl_order.return_value = {
        "status": "ok", "nrcvb_buy_qty": 100,
    }
    adapter.inquire_balance.return_value = {
        "status": "ok",
        "holdings": [{"symbol": "005930", "qty": "10", "avg_price": "72000"}],
        "summary": {"deposit": "10000000"},
    }
    return adapter


def _buy_req(symbol="005930", qty=10, price=72_000) -> OrderRequest:
    return OrderRequest(symbol=symbol, side="buy", qty=qty,
                        price=price, order_type="limit", reason="entry_1")


def _sell_req(symbol="005930", qty=5, price=73_440) -> OrderRequest:
    return OrderRequest(symbol=symbol, side="sell", qty=qty,
                        price=price, order_type="limit", reason="exit_tp1")


class _MarketOpenDatetime:
    @staticmethod
    def now():
        return MagicMock(time=MagicMock(return_value=time(10, 0)))


@pytest.mark.asyncio
async def test_executor_submit_dry_run_returns_order_no():
    ex = OrderExecutor(_make_adapter(), env="demo", dry_run=True)
    order_no = await ex.submit(_buy_req())
    assert order_no is not None


@pytest.mark.asyncio
async def test_executor_submit_real_calls_adapter():
    adapter = _make_adapter()
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    with patch("src.trading.scalping.order_executor.datetime", _MarketOpenDatetime):
        order_no = await ex.submit(_buy_req())
    assert order_no == "001"
    adapter.place_order_cash.assert_called_once()


@pytest.mark.asyncio
async def test_executor_passes_sor_exchange_id():
    adapter = _make_adapter()
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    req = OrderRequest(
        symbol="005930", side="sell", qty=1, price=72000,
        order_type="limit", reason="exit_next_open",
        preferred_venue=ExecutionVenue.SOR,
        venue_policy=VenuePolicy.SOR_BEST_EXECUTION,
    )
    with patch("src.trading.scalping.order_executor.datetime", _MarketOpenDatetime):
        order_no = await ex.submit(req)
    assert order_no == "001"
    assert adapter.place_order_cash.call_args.kwargs["excg_id"] == "SOR"


@pytest.mark.asyncio
async def test_executor_blocks_direct_nxt_in_vts_real_mode():
    adapter = _make_adapter()
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    req = OrderRequest(
        symbol="005930", side="buy", qty=1, price=72000,
        order_type="limit", reason="nxt_direct_probe",
        preferred_venue=ExecutionVenue.NXT,
        venue_policy=VenuePolicy.NXT_ONLY,
    )
    with patch("src.trading.scalping.order_executor.datetime", _MarketOpenDatetime):
        order_no = await ex.submit(req)
    assert order_no is None
    adapter.place_order_cash.assert_not_called()


@pytest.mark.asyncio
async def test_executor_submit_retries_on_error():
    adapter = _make_adapter()
    # 첫 2회 실패, 3회째 성공
    adapter.place_order_cash.side_effect = [
        {"status": "error", "error": "timeout"},
        {"status": "error", "error": "timeout"},
        {"status": "ok", "order_no": "002", "krx_org_no": "99999"},
    ]
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    # retry delay를 0으로 패치
    with patch("src.trading.scalping.order_executor.ORDER_RETRY_DELAY_SEC", 0.0), \
         patch("src.trading.scalping.order_executor.datetime", _MarketOpenDatetime):
        order_no = await ex.submit(_buy_req())
    assert order_no == "002"
    assert adapter.place_order_cash.call_count == 3


@pytest.mark.asyncio
async def test_executor_submit_vi_error_no_retry():
    adapter = _make_adapter()
    adapter.place_order_cash.return_value = {
        "status": "error", "error": "VI발동 거래정지",
    }
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    with patch("src.trading.scalping.order_executor.datetime", _MarketOpenDatetime):
        order_no = await ex.submit(_buy_req())
    assert order_no is None
    assert adapter.place_order_cash.call_count == 1   # 재시도 없음


@pytest.mark.asyncio
async def test_executor_wait_fill_dry_run_immediate():
    ex = OrderExecutor(_make_adapter(), env="demo", dry_run=True)
    order_no = await ex.submit(_buy_req())
    fill = await ex.wait_fill(order_no)
    assert fill is not None
    assert fill.symbol == "005930"
    assert fill.side == "buy"
    assert fill.filled_qty == 10
    assert fill.commission > 0


@pytest.mark.asyncio
async def test_executor_dry_run_order_blocks_api_but_simulates_fill():
    adapter = _make_adapter()
    ex = OrderExecutor(adapter, env="demo", dry_run=False, dry_run_order=True)
    from src.trading.scalping.events import TickEvent
    ex.update_market_snapshot(TickEvent(
        symbol="005930",
        price=72_000,
        buy_vol_total=1_000,
        sell_vol_total=900,
        bid_qty=1_000,
        ask_qty=1_000,
        tick_vol=10,
        acml_vol=10_000,
        acml_tr_pbmn=720_000_000,
        time_str="100000",
        bid1_price=71_950,
        ask1_price=72_050,
    ))

    order_no = await ex.submit(_buy_req(price=72_100))
    fill = await ex.wait_fill(order_no)

    assert order_no is not None
    adapter.place_order_cash.assert_not_called()
    assert fill is not None
    assert fill.filled_qty == 10
    assert fill.fill_price > 0


@pytest.mark.asyncio
async def test_executor_cancel_dry_run():
    ex = OrderExecutor(_make_adapter(), env="demo", dry_run=True)
    order_no = await ex.submit(_buy_req())
    ok = await ex.cancel_pending(order_no)
    assert ok is True
    assert ex._records[order_no].status.value == "canceled"


@pytest.mark.asyncio
async def test_executor_cancel_real():
    adapter = _make_adapter()
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    with patch("src.trading.scalping.order_executor.datetime", _MarketOpenDatetime):
        order_no = await ex.submit(_buy_req())
    ok = await ex.cancel_pending(order_no)
    assert ok is True
    adapter.cancel_order.assert_called_once()


def test_executor_slippage_check():
    ex = OrderExecutor(_make_adapter(), env="demo", dry_run=True)
    # check_slippage returns (exceeded: bool, pct: float)
    exceeded, pct = ex.check_slippage(72_000, 72_300, "buy")
    assert exceeded is True    # 0.4% > 0.3%
    assert pct > 0
    exceeded, _ = ex.check_slippage(72_000, 72_100, "buy")
    assert exceeded is False   # 0.14%
    # sell: fill_price 너무 낮음
    exceeded, _ = ex.check_slippage(72_000, 71_700, "sell")
    assert exceeded is True
    exceeded, _ = ex.check_slippage(72_000, 71_900, "sell")
    assert exceeded is False


@pytest.mark.asyncio
async def test_executor_get_buyable_qty_dry_run():
    ex = OrderExecutor(_make_adapter(), env="demo", dry_run=True)
    qty = await ex.get_buyable_qty("005930", 72_000)
    assert qty == 9999


@pytest.mark.asyncio
async def test_executor_get_buyable_qty_real():
    adapter = _make_adapter()
    ex = OrderExecutor(adapter, env="demo", dry_run=False)
    qty = await ex.get_buyable_qty("005930", 72_000)
    assert qty == 100
    adapter.inquire_psbl_order.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# MarketScanner — 필터
# ─────────────────────────────────────────────────────────────────────────────

def _make_scanner() -> MarketScanner:
    adapter = MagicMock()
    adapter.get_volume_ranking.return_value = {"status": "ok", "items": []}
    adapter.get_quote.return_value = {
        "status": "ok",
        "quote": {"change_rate": -0.5, "last": 900.0},
    }
    return MarketScanner(adapter, env="demo")


def _candidate(**kwargs) -> SymbolCandidate:
    defaults = dict(
        symbol="005930", name="삼성전자",
        price=72_000, change_pct=0.05,
        trading_value=10_000_000_000,
        volume=100_000, exec_strength=160,
    )
    defaults.update(kwargs)
    return SymbolCandidate(**defaults)


def test_scanner_filter_passes_valid():
    sc = _make_scanner()
    c = _candidate()
    assert sc._passes_filter(c) is True


def test_scanner_filter_price_too_low():
    sc = _make_scanner()
    c = _candidate(price=500)   # < MIN_PRICE=1000
    assert sc._passes_filter(c) is False


def test_scanner_filter_trading_value_too_low():
    sc = _make_scanner()
    c = _candidate(trading_value=1_000_000_000)   # 10억 < 50억
    assert sc._passes_filter(c) is False


def test_scanner_filter_change_too_low():
    sc = _make_scanner()
    c = _candidate(change_pct=0.01)   # 1% < 3%
    assert sc._passes_filter(c) is False


def test_scanner_filter_change_too_high():
    sc = _make_scanner()
    c = _candidate(change_pct=0.16)   # 16% > 15%
    assert sc._passes_filter(c) is False


def test_scanner_filter_vi_blocked():
    sc = _make_scanner()
    c = _candidate(is_vi=True)
    assert sc._passes_filter(c) is False


def test_scanner_filter_etf_name_prefix_blocked():
    sc = _make_scanner()
    c = _candidate(name="TIGER 코리아휴머노이드로봇산업")
    assert sc._passes_filter(c) is False


def test_scanner_vol_ratio():
    c = _candidate(volume=300_000, prev_same_time_vol=100_000)
    assert c.vol_ratio == pytest.approx(3.0)


def test_scanner_vol_ratio_zero_prev():
    c = _candidate(volume=300_000, prev_same_time_vol=0)
    assert c.vol_ratio == 0.0


@pytest.mark.asyncio
async def test_scanner_run_scan_market_halted():
    sc = _make_scanner()
    sc._kosdaq_change_pct = -0.02   # -2% < -1.5% → 차단
    with patch.object(sc, "_update_kosdaq", return_value=None):
        result = await sc.run_scan()
    assert result == []


@pytest.mark.asyncio
async def test_scanner_run_scan_returns_filtered():
    adapter = MagicMock()
    adapter.get_volume_ranking.return_value = {
        "status": "ok",
        "items": [
            {
                "symbol": "005930", "name": "삼성전자",
                "price": 72_000, "change_rate": 0.05,
                "trading_value": 10_000_000_000,
                "volume": 100_000, "exec_strength": 160,
            },
            {
                "symbol": "000001", "name": "동전주",
                "price": 300, "change_rate": 0.10,    # 가격 너무 낮음
                "trading_value": 1_000_000_000,
                "volume": 50_000, "exec_strength": 100,
            },
        ],
    }
    sc = MarketScanner(adapter, env="demo")
    sc._kosdaq_change_pct = 0.005   # 양호

    async def noop(*args, **kwargs): pass
    with patch.object(sc, "_update_kosdaq", noop):
        result = await sc.run_scan()

    assert len(result) == 1
    assert result[0].symbol == "005930"
    assert result[0].leader_rank == 1
    assert result[0].leader_score > 0


# ─────────────────────────────────────────────────────────────────────────────
# InMemoryStateStore
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_store_save_load_position():
    store = InMemoryStateStore()
    await store.save_position("005930", {"avg_price": 72000, "qty": 10})
    positions = await store.load_positions()
    assert "005930" in positions
    assert positions["005930"]["avg_price"] == 72000


@pytest.mark.asyncio
async def test_state_store_delete_position():
    store = InMemoryStateStore()
    await store.save_position("005930", {"qty": 10})
    await store.delete_position("005930")
    positions = await store.load_positions()
    assert "005930" not in positions


@pytest.mark.asyncio
async def test_state_store_risk():
    store = InMemoryStateStore()
    assert await store.load_risk() is None
    await store.save_risk({"realized_pnl": -50000, "is_halted": False})
    risk = await store.load_risk()
    assert risk["realized_pnl"] == -50000


@pytest.mark.asyncio
async def test_state_store_log_trade():
    store = InMemoryStateStore()
    await store.log_trade({
        "symbol": "005930", "side": "sell", "filled_qty": 3,
        "fill_price": 73440, "net_pnl": 4320, "reason": "exit_tp1",
    })
    trades = await store.get_trades_today()
    assert len(trades) == 1
    assert trades[0]["symbol"] == "005930"


@pytest.mark.asyncio
async def test_make_state_store_no_redis_returns_inmemory():
    from src.trading.scalping.config import ScalpingBotConfig
    cfg = ScalpingBotConfig()
    cfg.redis.enabled = False
    store = await make_state_store(cfg)
    assert isinstance(store, InMemoryStateStore)
