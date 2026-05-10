from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.brokers.kis import KISBrokerAdapter
from src.trading.scalping.after_market_engine import AfterMarketEngine
from src.trading.scalping.closing_bet_results import (
    ClosingBetResultStore,
    gap_pct,
    net_pnl_after_costs,
)
from src.trading.scalping.closing_bet_scanner import CloseBetScanner
from src.trading.scalping.events import FillEvent
from src.trading.scalping.position_manager import PositionManager
from src.trading.scalping.position_type import PositionType
from src.trading.scalping.risk_manager import RiskManager
from src.trading.scalping.constants import CLOSE_BET_START_TIME, NEXT_OPEN_EXIT_START
from src.trading.scalping.market_regime import MarketRegime
from src.trading.scalping.nxt_market import choose_routing
from src.trading.scalping.venue import (
    ExecutionVenue,
    ListingMarket,
    MarketSession,
    VenueCapability,
    VenuePolicy,
    evaluate_venue_gap,
    NxtMarketContext,
    VenueSignal,
)


class _Adapter:
    def __init__(self, items=None, kosdaq=0.0, book=None, nxt=None):
        self.items = items or []
        self.kosdaq = kosdaq
        self.book = book or {}
        self.nxt = nxt or {}

    def get_volume_ranking(self, top_n=30, env_dv="demo"):
        return {"status": "ok", "items": self.items[:top_n]}

    def get_quote(self, symbol, market_code="U", env_dv="demo"):
        return {"status": "ok", "quote": {"change_rate": self.kosdaq * 100}}

    def get_order_book(self, symbol, env_dv="demo"):
        return {"status": "ok", "order_book": self.book}

    def get_nxt_market_context(self, symbol, session="nxt_after", env_dv="demo"):
        return self.nxt.get((symbol, session), self.nxt.get(symbol, {"status": "missing"}))


class _Signal:
    def __init__(self, samples):
        self.samples = samples

    def get_exec_strength_samples(self, symbol, lookback_minutes=30):
        return self.samples.get(symbol, [])


def _item(symbol="005930", **overrides):
    data = {
        "symbol": symbol,
        "name": "삼성전자",
        "price": 70000,
        "change_rate": 0.06,
        "vi_count_60m": 0,
        "trading_value": 150e9,
    }
    data.update(overrides)
    return data


def test_close_bet_scanner_filters_and_exec_strength_avg():
    scanner = CloseBetScanner(
        _Adapter(items=[
            _item("005930"),
            _item("000660", vi_count_60m=1),
            _item("035420", trading_value=90e9),
        ], kosdaq=0.002),
        _Signal({"005930": [110, 120, 130], "000660": [130, 130, 130], "035420": [130, 130, 130]}),
        PositionManager(),
    )

    assert scanner.exec_strength_30m_avg("005930") == pytest.approx(120)
    candidates = scanner.scan()
    assert [c.symbol for c in candidates] == ["005930"]


def test_close_bet_scanner_nxt_missing_falls_back_to_krx_only():
    scanner = CloseBetScanner(
        _Adapter(items=[_item("005930")], kosdaq=0.002),
        _Signal({"005930": [130, 130, 130]}),
        PositionManager(),
    )
    candidate = scanner.scan()[0]
    assert candidate.strategy_id == "close_bet_krx_only"
    assert candidate.nxt_metadata["nxt_data_missing"] is True
    assert candidate.nxt_score_adjustment < 0


def test_close_bet_scanner_nxt_supportive_sets_nxt_aware_score():
    scanner = CloseBetScanner(
        _Adapter(
            items=[_item("005930", price=70_000, trading_value=200e9)],
            kosdaq=0.002,
            nxt={
                ("005930", MarketSession.NXT_AFTER.value): {
                    "status": "ok",
                    "nxt_price": 70_700,
                    "nxt_turnover": 8e9,
                    "nxt_volume": 120_000,
                    "nxt_spread": 0.001,
                    "nxt_bid_ask_imbalance": 1.3,
                }
            },
        ),
        _Signal({"005930": [130, 130, 130]}),
        PositionManager(),
    )
    candidate = scanner.scan()[0]
    assert candidate.strategy_id == "close_bet_nxt_aware"
    assert candidate.nxt_metadata["venue_gap_reason"] == "nxt_premium_liquid"
    assert candidate.nxt_score_adjustment > 0


def test_close_bet_scanner_keeps_nxt_exhaustion_as_exit_priority():
    scanner = CloseBetScanner(
        _Adapter(
            items=[_item("005930", price=70_000, trading_value=200e9)],
            kosdaq=0.002,
            nxt={
                ("005930", MarketSession.NXT_AFTER.value): {
                    "status": "ok",
                    "nxt_price": 72_000,
                    "nxt_turnover": 8e9,
                    "nxt_volume": 120_000,
                    "nxt_spread": 0.012,
                    "nxt_bid_ask_imbalance": 1.1,
                    "turnover_slope": -1.0,
                    "trade_count_slope": -1.0,
                    "price_momentum_10m": 0.02,
                    "bid_cancel_rate": 0.8,
                    "bid_wall_fill_ratio": 0.05,
                }
            },
        ),
        _Signal({"005930": [130, 130, 130]}),
        PositionManager(),
    )
    candidates = scanner.scan()
    assert len(candidates) == 1
    assert candidates[0].strategy_id == "close_bet_nxt_exit_priority"
    assert candidates[0].close_bet_grade == "c_exit_priority"
    assert candidates[0].position_size_multiplier <= 0.5
    assert candidates[0].morning_exit_priority >= 60
    assert scanner.last_diagnostics["fail_overnight_risk"] == 0


def test_close_bet_scanner_preserves_thin_but_resilient_nxt_candidate():
    scanner = CloseBetScanner(
        _Adapter(
            items=[_item("005930", price=70_000, trading_value=200e9)],
            kosdaq=0.002,
            nxt={
                ("005930", MarketSession.NXT_AFTER.value): {
                    "status": "ok",
                    "nxt_price": 70_200,
                    "nxt_turnover": 1e9,
                    "nxt_volume": 10_000,
                    "nxt_spread": 0.001,
                    "nxt_bid_ask_imbalance": 1.0,
                    "time_above_krx_close_ratio": 0.90,
                    "sell_shock_recovery_pct": 0.80,
                    "spread_stability": 0.85,
                    "bid_absorption_strength": 0.70,
                    "price_hold_under_thin_liquidity": 0.90,
                }
            },
        ),
        _Signal({"005930": [130, 130, 130]}),
        PositionManager(),
    )
    candidates = scanner.scan()
    assert len(candidates) == 1
    assert candidates[0].close_bet_grade in {"a_hold_candidate", "b_keep_candidate"}
    assert candidates[0].score > 0


def test_close_bet_near_miss_and_diagnostics_counts():
    scanner = CloseBetScanner(
        _Adapter(items=[
            _item("005930", trading_value=150e9),
            _item("000660", trading_value=90e9),
        ], kosdaq=0.002),
        _Signal({"005930": [106, 106, 106], "000660": [130, 130, 130]}),
        PositionManager(),
    )
    assert scanner.scan() == []
    diag = scanner.last_diagnostics
    assert diag["near_miss"] == 1
    assert diag["fail_exec_strength_30m"] == 1
    assert diag["fail_trading_value"] == 1


def test_venue_gap_discount_liquid_is_risk():
    ctx = NxtMarketContext(
        symbol="005930",
        session=MarketSession.NXT_AFTER,
        nxt_price=69_000,
        nxt_turnover=5e9,
        krx_reference_price=70_000,
        krx_turnover=100e9,
        data_quality="ok",
    )
    decision = evaluate_venue_gap(ctx)
    assert decision.signal == VenueSignal.RISK
    assert decision.reason == "nxt_discount_liquid"


def test_sor_routes_when_supported_in_demo_real():
    route = choose_routing(
        VenueCapability(sor_order=True),
        requested_policy=VenuePolicy.SOR_BEST_EXECUTION,
        env="demo",
        dry_run=False,
    )
    assert route.venue_policy == VenuePolicy.SOR_BEST_EXECUTION
    assert route.preferred_venue == ExecutionVenue.SOR


def test_direct_nxt_fallback_to_krx_when_vts_unsupported():
    route = choose_routing(
        VenueCapability(nxt_order=True, vts_nxt_supported=False),
        requested_policy=VenuePolicy.NXT_ONLY,
        env="demo",
        dry_run=False,
    )
    assert route.venue_policy == VenuePolicy.FALLBACK_KRX
    assert route.reason == "vts_nxt_direct_order_unsupported"


def test_close_bet_scanner_blocks_bad_kosdaq_and_intraday_symbol():
    mgr = PositionManager()
    mgr.on_fill_entry(
        FillEvent("1", "005930", "buy", 1, 70000, 0, 0),
        atr=500,
        position_type=PositionType.INTRADAY_SCALP,
    )
    bad_index = CloseBetScanner(
        _Adapter(items=[_item("005930")], kosdaq=-0.006),
        _Signal({"005930": [130, 130, 130]}),
        PositionManager(),
    )
    assert bad_index.scan() == []

    scanner = CloseBetScanner(
        _Adapter(items=[_item("005930")], kosdaq=0.002),
        _Signal({"005930": [130, 130, 130]}),
        mgr,
    )
    assert scanner.scan() == []


def test_overnight_risk_limits_per_symbol_and_total():
    rm = RiskManager(capital=1_000_000)
    ok, reason = rm.approve_entry(
        "005930", amount=60_000, current_positions_count=0, total_exposure=0,
        position_type=PositionType.CLOSE_BET, kosdaq_change_pct=0.0,
    )
    assert not ok
    assert "종목당" in reason

    ok, reason = rm.approve_entry(
        "005930", amount=40_000, current_positions_count=0, total_exposure=130_000,
        position_type=PositionType.CLOSE_BET, overnight_total_exposure=130_000,
        kosdaq_change_pct=0.0,
    )
    assert not ok
    assert "전체" in reason


def test_kis_ord_dvsn_override_requires_price_and_sets_07():
    adapter = KISBrokerAdapter(app_key="k", app_secret="s", account_no="12345678-01")
    result = adapter.place_order_cash(
        "005930", "buy", qty=1, price=70000, dry_run=True,
        ord_dvsn_override="07",
    )
    assert result["ord_dvsn"] == "07"
    assert result["ord_unpr"] != "0"

    with pytest.raises(ValueError):
        adapter.place_order_cash(
            "005930", "buy", qty=1, price=0, dry_run=True,
            ord_dvsn_override="07",
        )


@pytest.mark.asyncio
async def test_after_market_demo_real_order_blocked_and_dry_run_allowed():
    mgr = PositionManager()
    mgr.on_fill_entry(
        FillEvent("1", "005930", "buy", 10, 70000, 0, 0),
        atr=500,
        position_type=PositionType.CLOSE_BET,
    )
    rm = RiskManager(capital=10_000_000)

    blocked = AfterMarketEngine(
        adapter=_Adapter(book={"bid_qty": 2000, "ask_qty": 1000, "price": 70100}),
        executor=MagicMock(),
        position_mgr=mgr,
        risk_mgr=rm,
        env="demo",
        dry_run=False,
    )
    with pytest.raises(RuntimeError):
        await blocked.add_position("005930", 1, 70100)

    executor = MagicMock()
    executor.submit = AsyncMock(return_value="D1")
    executor.wait_fill = AsyncMock(return_value=FillEvent("D1", "005930", "buy", 1, 70100, 0, 0))
    allowed = AfterMarketEngine(
        adapter=_Adapter(book={"bid_qty": 2000, "ask_qty": 1000, "price": 70100}),
        executor=executor,
        position_mgr=mgr,
        risk_mgr=rm,
        env="demo",
        dry_run=True,
    )
    fill = await allowed.add_position("005930", 1, 70100)
    assert fill is not None
    req = executor.submit.await_args.args[0]
    assert req.ord_dvsn_override == "07"
    assert req.position_type == PositionType.CLOSE_BET
    assert req.market_session == MarketSession.NXT_AFTER
    assert req.preferred_venue == ExecutionVenue.NXT


@pytest.mark.asyncio
async def test_after_market_unfilled_cancels_without_retry():
    executor = MagicMock()
    executor.cancel_pending = AsyncMock(return_value=True)
    engine = AfterMarketEngine(
        adapter=_Adapter(),
        executor=executor,
        position_mgr=PositionManager(),
        risk_mgr=RiskManager(capital=1_000_000),
        dry_run=True,
    )
    assert await engine.handle_unfilled("O1") is True
    executor.cancel_pending.assert_awaited_once_with("O1")


def test_closing_bet_results_jsonl_and_calculations(tmp_path: Path):
    store = ClosingBetResultStore(tmp_path)
    path = store.append({
        "symbol": "005930",
        "entry_price": 10000,
        "exit_price": 10300,
        "gap_pct": gap_pct(10000, 10300),
        "net_pnl": net_pnl_after_costs(10000, 10300, 10, 15, 10),
    })
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["position_type"] == "close_bet"
    assert row["gap_pct"] == pytest.approx(0.03)
    assert row["net_pnl"] == pytest.approx(2975)


@pytest.mark.asyncio
async def test_closing_bet_loop_time_gate_1449_1450_1515():
    from src.trading.scalping.bot import BotStatus, ScalpingBot

    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()
    bot._market_halted = False
    bot._regime_analyzer = SimpleNamespace(
        current_policy=SimpleNamespace(regime=MarketRegime.KOSDAQ_NORMAL)
    )
    bot._close_bet_scanner = MagicMock()
    bot._close_bet_scanner.scan.return_value = []
    bot._execute_close_bet_entry = AsyncMock()

    class _FakeDT:
        def __init__(self, t):
            self._t = t
        def time(self):
            return self._t

    async def _one_sleep(_seconds):
        bot._kill_event.set()

    for t, expected_calls in [
        (CLOSE_BET_START_TIME.replace(minute=49), 0),
        (CLOSE_BET_START_TIME, 1),
        (CLOSE_BET_START_TIME.replace(hour=15, minute=16), 0),
    ]:
        bot._kill_event = asyncio.Event()
        bot._close_bet_scanner.scan.reset_mock()

        class _MockDatetime:
            @staticmethod
            def now():
                return _FakeDT(t)

        with patch("src.trading.scalping.bot.datetime", _MockDatetime), \
             patch("src.trading.scalping.bot.asyncio.sleep", AsyncMock(side_effect=_one_sleep)):
            await bot._closing_bet_loop()
        assert bot._close_bet_scanner.scan.call_count == expected_calls


@pytest.mark.asyncio
async def test_next_open_exit_engine_exits_only_close_bet_positions():
    from src.trading.scalping.bot import BotStatus, ScalpingBot

    mgr = PositionManager()
    mgr.on_fill_entry(
        FillEvent("1", "005930", "buy", 10, 70000, 0, 0),
        atr=500,
        position_type=PositionType.CLOSE_BET,
    )
    mgr.on_fill_entry(
        FillEvent("2", "000660", "buy", 10, 100000, 0, 0),
        atr=500,
        position_type=PositionType.INTRADAY_SCALP,
    )

    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()
    bot._position_mgr = mgr
    bot._signal_engine = MagicMock()
    bot._signal_engine.get_last_price.return_value = 71000
    bot._execute_exit = AsyncMock()

    class _FakeDT:
        def time(self):
            return NEXT_OPEN_EXIT_START

    class _MockDatetime:
        @staticmethod
        def now():
            return _FakeDT()

    async def _one_sleep(_seconds):
        bot._kill_event.set()

    with patch("src.trading.scalping.bot.datetime", _MockDatetime), \
         patch("src.trading.scalping.bot.asyncio.sleep", AsyncMock(side_effect=_one_sleep)):
        await bot._next_open_exit_engine()

    await asyncio.sleep(0)
    assert bot._execute_exit.await_count == 1
    req = bot._execute_exit.await_args.args[0]
    assert req.symbol == "005930"
    assert req.position_type == PositionType.CLOSE_BET


def test_position_snapshot_restores_venue_fields():
    pos = PositionManager().restore_position({
        "symbol": "005930",
        "avg_price": 70_000,
        "entry_price": 70_000,
        "remaining_qty": 10,
        "total_qty": 10,
        "phase": "entering",
        "position_type": "close_bet",
        "listing_market": "kosdaq",
        "preferred_venue": "sor",
        "actual_venue": "nxt",
        "venue_policy": "sor_best_execution",
        "market_session": "krx_close_auction",
        "krx_entry_price": 70_000,
        "nxt_reference_price": 70_700,
        "venue_price_gap_at_entry": 0.01,
        "nxt_after_signal": "nxt_premium_liquid",
        "nxt_pre_signal": "nxt_pre_data_missing",
    })
    assert pos.listing_market == ListingMarket.KOSDAQ
    assert pos.preferred_venue == ExecutionVenue.SOR
    assert pos.actual_venue == ExecutionVenue.NXT
    assert pos.venue_policy == VenuePolicy.SOR_BEST_EXECUTION
    assert pos.market_session == MarketSession.KRX_CLOSE_AUCTION
    assert pos.nxt_reference_price == pytest.approx(70_700)
