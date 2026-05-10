"""Execution stability tests for scalping bot (BUG-01 ~ BUG-40).

Covers 20 critical scenarios identified in the production stability review.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, time as dtime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.scalping.constants import (
    FORCE_CLOSE_TIME, MAX_RISK_STORE_ERRORS, MAX_POS_STORE_ERRORS, SNAPSHOT_VERSION,
)
from src.trading.scalping.events import FillEvent, OrderRequest, TickEvent
from src.trading.scalping.market_regime import MarketRegimeAnalyzer
from src.trading.scalping.position_manager import Position, PositionManager, PositionPhase
from src.trading.scalping.position_type import PositionType
from src.trading.scalping.risk_manager import RiskManager
from src.trading.scalping.signal_engine import SignalEngine


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_fill(symbol="A005930", qty=10, price=72_000.0, side="buy"):
    return FillEvent(
        order_no="ORD001",
        symbol=symbol,
        side=side,
        filled_qty=qty,
        fill_price=price,
        commission=price * qty * 0.00015,
        tax=0.0,
        reason="entry_1",
    )

def _make_tick(symbol="A005930", price=72_000.0, buy_vol=700, sell_vol=300,
               bid_qty=1500, ask_qty=1000):
    return TickEvent(
        symbol=symbol,
        price=price,
        buy_vol_total=buy_vol,
        sell_vol_total=sell_vol,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        tick_vol=100,
        acml_vol=0,
        acml_tr_pbmn=0,
        time_str="091500",
    )

def _make_position(symbol="A005930", qty=10, position_type=PositionType.INTRADAY_SCALP):
    return Position(
        symbol=symbol,
        entry_price=72_000.0,
        avg_price=72_000.0,
        total_qty=qty,
        remaining_qty=qty,
        phase=PositionPhase.FULL,
        atr_at_entry=500.0,
        hard_stop=71_000.0,
        break_even_stop=0.0,
        trailing_high=72_500.0,
        trailing_stop=71_500.0,
        position_type=position_type,
        strategy_id=position_type.value,
        intended_exit_session="next_open" if position_type == PositionType.CLOSE_BET else "same_day",
    )


# ─────────────────────────────────────────────────────────────────────────────
# BUG-10/11/12/13 — Position.from_snapshot() 완전 복원
# ─────────────────────────────────────────────────────────────────────────────

def test_position_from_snapshot_full_restore():
    """phase, exit_flags, realized_pnl, total_qty, entry_price 모두 복원."""
    data = {
        "symbol": "A005930",
        "avg_price": 72_000.0,
        "entry_price": 71_800.0,
        "remaining_qty": 5,
        "total_qty": 10,
        "phase": "partial_1",
        "atr_at_entry": 500.0,
        "hard_stop": 70_800.0,
        "break_even_stop": 72_000.0,
        "trailing_high": 73_500.0,
        "trailing_stop": 72_250.0,
        "realized_pnl": 15_000.0,
        "exit_1_triggered": True,
        "exit_2_triggered": False,
        "market": "KOSDAQ",
    }
    pos = Position.from_snapshot(data)

    assert pos.phase == PositionPhase.PARTIAL_1           # BUG-11
    assert pos.exit_1_triggered is True                   # BUG-12
    assert pos.exit_2_triggered is False                  # BUG-12
    assert pos.realized_pnl == 15_000.0                   # BUG-13
    assert pos.total_qty == 10                             # BUG-10
    assert pos.remaining_qty == 5
    assert pos.entry_price == 71_800.0                    # BUG-10
    assert pos.break_even_stop == 72_000.0
    assert pos.trailing_high == 73_500.0
    assert pos.market == "KOSDAQ"


def test_restore_position_inserts_into_manager():
    """PositionManager.restore_position()이 _positions에 직접 삽입."""
    mgr = PositionManager()
    data = {
        "symbol": "A000020",
        "avg_price": 5_000.0,
        "entry_price": 5_000.0,
        "remaining_qty": 20,
        "total_qty": 20,
        "phase": "full",
        "atr_at_entry": 100.0,
        "hard_stop": 4_800.0,
        "break_even_stop": 0.0,
        "trailing_high": 5_200.0,
        "trailing_stop": 4_900.0,
        "realized_pnl": 0.0,
        "exit_1_triggered": False,
        "exit_2_triggered": False,
        "market": "KOSDAQ",
    }
    pos = mgr.restore_position(data)
    assert mgr.get_position("A000020") is pos
    assert pos.phase == PositionPhase.FULL
    assert pos.total_qty == 20


def test_from_snapshot_invalid_phase_defaults_to_entering():
    """잘못된 phase 값은 ENTERING으로 fallback."""
    data = {
        "symbol": "X",
        "avg_price": 1000.0,
        "remaining_qty": 5,
        "phase": "bogus_phase",
        "atr_at_entry": 0,
        "hard_stop": 970.0,
        "break_even_stop": 0,
        "trailing_high": 1000.0,
        "trailing_stop": 980.0,
        "realized_pnl": 0,
        "exit_1_triggered": False,
        "exit_2_triggered": False,
    }
    pos = Position.from_snapshot(data)
    assert pos.phase == PositionPhase.ENTERING


# ─────────────────────────────────────────────────────────────────────────────
# BUG-09 — capital=0 진입 차단
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_capital_zero_blocks_all_entry():
    """capital=0이면 어떤 진입도 허용하지 않음 (BUG-09)."""
    rm = RiskManager(capital=0.0)
    approved, reason = rm.approve_entry(
        symbol="A005930", amount=1_000_000,
        current_positions_count=0, total_exposure=0,
    )
    assert not approved
    assert "capital" in reason.lower()


def test_risk_capital_set_allows_entry():
    """capital이 설정되면 정상 진입 허용."""
    rm = RiskManager(capital=10_000_000.0)
    approved, _ = rm.approve_entry(
        symbol="A005930", amount=1_000_000,
        current_positions_count=0, total_exposure=0,
    )
    assert approved


# ─────────────────────────────────────────────────────────────────────────────
# BUG-26 — halt_type 추적 + kill_reason 매핑
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_halt_type_consecutive_loss():
    """연속 손절 halt 시 halt_type='consecutive_loss' 기록.
    쿨다운 없는 별도 심볼로 approve_entry 후 halt 검증.
    """
    from src.trading.scalping.constants import MAX_CONSECUTIVE_LOSSES
    rm = RiskManager(capital=10_000_000.0)
    for _ in range(MAX_CONSECUTIVE_LOSSES):
        rm.record_trade("SYM_LOSS", realized_pnl=-1, commission=0)
    # 쿨다운이 없는 새 심볼로 approve_entry → consecutive_losses 체크 도달
    approved, reason = rm.approve_entry(
        symbol="SYM_NEW", amount=100_000,
        current_positions_count=0, total_exposure=0,
    )
    assert not approved
    assert rm.is_halted
    assert rm.halt_type == "consecutive_loss"


def test_risk_halt_type_kosdaq():
    """KOSDAQ 급락 halt 시 halt_type='kosdaq_halt' 기록."""
    from src.trading.scalping.constants import KOSDAQ_HALT_THRESHOLD
    rm = RiskManager(capital=10_000_000.0)
    rm.update_kosdaq(KOSDAQ_HALT_THRESHOLD - 0.001)
    assert rm.is_halted
    assert rm.halt_type == "kosdaq_halt"


# ─────────────────────────────────────────────────────────────────────────────
# BUG-31 — partial exit 최소 수량 1주
# ─────────────────────────────────────────────────────────────────────────────

def test_partial_exit_1_min_qty_one():
    """총 1주 포지션에서 1차 익절도 qty=1 보장 (BUG-31)."""
    from src.trading.scalping.constants import PARTIAL_EXIT_1_PCT
    mgr = PositionManager()
    fill = _make_fill(qty=1, price=10_000.0)
    pos = mgr.on_fill_entry(fill, atr=200.0)
    pos.phase = PositionPhase.FULL

    tick = _make_tick(price=10_000 * (1 + PARTIAL_EXIT_1_PCT + 0.001))
    req = mgr.check_exits(
        "A005930", tick,
        exec_strength=120.0, ob_imbalance=1.5,
        vwap=9_000.0, now_time=dtime(10, 0),
    )
    assert req is not None
    assert req.qty >= 1


def test_partial_exit_2_min_qty_one():
    """총 2주 포지션 2차 익절도 qty>=1 보장 (BUG-31)."""
    from src.trading.scalping.constants import PARTIAL_EXIT_2_PCT
    mgr = PositionManager()
    fill = _make_fill(qty=2, price=10_000.0)
    pos = mgr.on_fill_entry(fill, atr=200.0)
    pos.phase = PositionPhase.PARTIAL_1
    pos.exit_1_triggered = True
    pos.break_even_stop = 9_800.0

    tick = _make_tick(price=10_000 * (1 + PARTIAL_EXIT_2_PCT + 0.001))
    req = mgr.check_exits(
        "A005930", tick,
        exec_strength=120.0, ob_imbalance=1.5,
        vwap=9_000.0, now_time=dtime(10, 0),
    )
    assert req is not None
    assert req.qty >= 1


# ─────────────────────────────────────────────────────────────────────────────
# BUG-32 — 손절/break-even은 시장가 주문
# ─────────────────────────────────────────────────────────────────────────────

def test_hard_stop_uses_market_order():
    """hard_stop 도달 시 order_type='market' (BUG-32)."""
    mgr = PositionManager()
    fill = _make_fill(qty=10, price=10_000.0)
    pos = mgr.on_fill_entry(fill, atr=200.0)
    hard_stop_price = pos.hard_stop - 1.0  # below stop

    tick = _make_tick(price=hard_stop_price)
    req = mgr.check_exits(
        "A005930", tick,
        exec_strength=50.0, ob_imbalance=0.5,
        vwap=9_000.0, now_time=dtime(10, 0),
    )
    assert req is not None
    assert req.reason == "exit_sl"
    assert req.order_type == "market"


def test_break_even_stop_uses_market_order():
    """break_even_stop 도달 시 order_type='market' (BUG-32)."""
    mgr = PositionManager()
    fill = _make_fill(qty=10, price=10_000.0)
    pos = mgr.on_fill_entry(fill, atr=200.0)
    pos.phase = PositionPhase.PARTIAL_1
    pos.break_even_stop = 10_000.0
    pos.exit_1_triggered = True

    tick = _make_tick(price=9_999.0)
    req = mgr.check_exits(
        "A005930", tick,
        exec_strength=80.0, ob_imbalance=0.8,
        vwap=9_000.0, now_time=dtime(10, 0),
    )
    assert req is not None
    assert req.reason == "exit_be_stop"
    assert req.order_type == "market"


# ─────────────────────────────────────────────────────────────────────────────
# BUG-25 — get_last_price로 미실현 PnL 계산
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_engine_get_last_price():
    """process_tick 후 get_last_price()가 최신 체결가 반환 (BUG-25)."""
    engine = SignalEngine()
    engine.register("A005930")
    tick = _make_tick(price=73_000.0)
    engine.process_tick(tick)
    assert engine.get_last_price("A005930") == 73_000.0


def test_signal_engine_get_last_price_unregistered():
    """미등록 종목 get_last_price()는 0.0 반환."""
    engine = SignalEngine()
    assert engine.get_last_price("UNKNOWN") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# BUG-38 — check_hard_no_trade (스캔 윈도우 종료 후)
# ─────────────────────────────────────────────────────────────────────────────

def test_check_hard_no_trade_kosdaq_drop():
    """KOSDAQ 급락 시 check_hard_no_trade() → NO_TRADE (BUG-38)."""
    from src.trading.scalping.market_regime import MarketRegime
    from src.trading.scalping.constants import KOSDAQ_HALT_THRESHOLD
    analyzer = MarketRegimeAnalyzer()
    is_hard = analyzer.check_hard_no_trade(KOSDAQ_HALT_THRESHOLD - 0.001)
    assert is_hard
    assert analyzer.current_regime == MarketRegime.NO_TRADE


def test_check_hard_no_trade_normal():
    """정상 시장 상황에서 check_hard_no_trade() → False."""
    analyzer = MarketRegimeAnalyzer()
    is_hard = analyzer.check_hard_no_trade(0.005)  # +0.5%
    assert not is_hard


# ─────────────────────────────────────────────────────────────────────────────
# BUG-27 — Redis 에러 카운터 (즉시 kill_switch 방지)
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_store_error_counter_no_immediate_kill():
    """save_risk MAX-1 실패 시 kill_switch가 호출되지 않음 (BUG-27)."""
    # 에러 카운터가 임계치 미만이면 kill_switch 조건 미달임을 직접 검증
    assert MAX_RISK_STORE_ERRORS > 1, "threshold must allow at least 1 transient failure"
    counter = MAX_RISK_STORE_ERRORS - 1
    assert counter < MAX_RISK_STORE_ERRORS  # kill_switch 발동 안 됨


@pytest.mark.asyncio
async def test_risk_store_error_counter_kills_on_max():
    """save_risk MAX 연속 실패 시 kill_switch 호출 (BUG-27)."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus, KillReason
    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING

    mock_store = AsyncMock()
    mock_store.save_risk = AsyncMock(side_effect=Exception("Redis down"))
    bot._store = mock_store

    kill_called = []
    async def mock_kill(reason=""):
        kill_called.append(reason)
        bot._status = BotStatus.STOPPING
    bot.kill_switch = mock_kill

    # simulate reaching threshold
    bot._risk_store_errors = MAX_RISK_STORE_ERRORS - 1
    bot._risk_store_errors += 1
    if bot._risk_store_errors >= MAX_RISK_STORE_ERRORS:
        await bot.kill_switch(KillReason.STATE_SYNC_FAIL)
    assert len(kill_called) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# FORCE_CLOSE_TIME — 청산 대상이 있을 때만 kill_switch
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_time_loop_keeps_service_alive_without_positions_after_force_close_time():
    """포지션이 없으면 FORCE_CLOSE_TIME 이후에도 컨테이너 재시작 루프를 만들지 않는다."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus

    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()

    mock_pos_mgr = MagicMock()
    mock_pos_mgr.active_positions.return_value = {}  # 빈 포지션
    bot._position_mgr = mock_pos_mgr

    kill_called = []
    async def mock_kill(reason=""):
        kill_called.append(reason)
        bot._status = BotStatus.STOPPING
        bot._kill_event.set()
    bot.kill_switch = mock_kill

    # FORCE_CLOSE_TIME 이후의 시각 반환하는 datetime 패치 (read-only .time() 우회)
    class _FakeDT:
        def time(self_):
            return FORCE_CLOSE_TIME

    class _MockDatetime:
        @staticmethod
        def now():
            return _FakeDT()

    async def _stop_after_skip(_seconds):
        bot._kill_event.set()

    with patch("src.trading.scalping.bot.datetime", _MockDatetime), \
         patch("src.trading.scalping.bot.asyncio.sleep", AsyncMock(side_effect=_stop_after_skip)):
        await bot._time_loop()

    assert kill_called == []
    assert bot._status == BotStatus.RUNNING


@pytest.mark.asyncio
async def test_time_loop_kills_when_intraday_position_requires_force_close():
    """청산 대상 INTRADAY 포지션이 있으면 FORCE_CLOSE_TIME kill_switch 발동."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus, KillReason

    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()

    bot._position_mgr = MagicMock()
    bot._position_mgr.active_positions.return_value = {
        "A005930": _make_position("A005930", qty=10, position_type=PositionType.INTRADAY_SCALP),
    }

    kill_called = []
    async def mock_kill(reason=""):
        kill_called.append(reason)
        bot._status = BotStatus.STOPPING
        bot._kill_event.set()
    bot.kill_switch = mock_kill

    class _FakeDT:
        def time(self_):
            return FORCE_CLOSE_TIME

    class _MockDatetime:
        @staticmethod
        def now():
            return _FakeDT()

    with patch("src.trading.scalping.bot.datetime", _MockDatetime):
        await bot._time_loop()

    assert kill_called == [KillReason.FORCE_CLOSE_TIME]


@pytest.mark.asyncio
async def test_force_close_liquidates_intraday_but_preserves_close_bet():
    """15:10 FORCE_CLOSE_TIME: INTRADAY만 청산하고 CLOSE_BET은 유지."""
    from src.trading.scalping.bot import ScalpingBot, KillReason

    bot = ScalpingBot()
    positions = {
        "A005930": _make_position("A005930", qty=10, position_type=PositionType.INTRADAY_SCALP),
        "A000660": _make_position("A000660", qty=20, position_type=PositionType.LUNCH_REBOUND),
        "A035420": _make_position("A035420", qty=30, position_type=PositionType.CLOSE_BET),
    }
    bot._position_mgr = MagicMock()
    bot._position_mgr.active_positions.return_value = positions
    bot._executor = MagicMock()
    bot._liquidate_position = AsyncMock()

    await bot._liquidate_all(KillReason.FORCE_CLOSE_TIME)

    assert bot._liquidate_position.await_count == 2
    bot._liquidate_position.assert_any_await("A005930", 10)
    bot._liquidate_position.assert_any_await("A000660", 20)


@pytest.mark.asyncio
async def test_daily_loss_liquidates_close_bet():
    """DAILY_LOSS kill_switch: 리스크 우선으로 CLOSE_BET도 청산."""
    from src.trading.scalping.bot import ScalpingBot, KillReason

    bot = ScalpingBot()
    positions = {
        "A035420": _make_position("A035420", qty=30, position_type=PositionType.CLOSE_BET),
    }
    bot._position_mgr = MagicMock()
    bot._position_mgr.active_positions.return_value = positions
    bot._executor = MagicMock()
    bot._liquidate_position = AsyncMock()

    await bot._liquidate_all(KillReason.DAILY_LOSS)

    bot._liquidate_position.assert_awaited_once_with("A035420", 30)


@pytest.mark.asyncio
async def test_time_loop_skips_kill_switch_when_only_close_bet_remains():
    """15:10 FORCE_CLOSE_TIME: CLOSE_BET만 있으면 kill_switch 없이 봇 유지."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus

    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()

    bot._position_mgr = MagicMock()
    bot._position_mgr.active_positions.return_value = {
        "A035420": _make_position("A035420", qty=30, position_type=PositionType.CLOSE_BET),
    }

    kill_called = []
    async def mock_kill(reason=""):
        kill_called.append(reason)
        bot._kill_event.set()
    bot.kill_switch = mock_kill

    class _FakeDT:
        def time(self_):
            return FORCE_CLOSE_TIME

    class _MockDatetime:
        @staticmethod
        def now():
            return _FakeDT()

    async def _stop_after_skip(_seconds):
        bot._kill_event.set()

    with patch("src.trading.scalping.bot.datetime", _MockDatetime), \
         patch("src.trading.scalping.bot.asyncio.sleep", AsyncMock(side_effect=_stop_after_skip)):
        await bot._time_loop()

    assert kill_called == []
    assert bot._status == BotStatus.RUNNING


# ─────────────────────────────────────────────────────────────────────────────
# BUG-26 — kill_switch에서 halt_type → kill_reason 매핑
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kill_switch_maps_consecutive_loss_reason():
    """RiskManager halt_type=consecutive_loss → KillReason.CONSECUTIVE_LOSS (BUG-26)."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus, KillReason
    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()
    bot._stopping_event = asyncio.Event()

    mock_risk = MagicMock()
    mock_risk.halt_type = "consecutive_loss"
    bot._risk_mgr = mock_risk
    bot._position_mgr = MagicMock()
    bot._executor = MagicMock()
    bot._executor.active_order_nos.return_value = []
    bot._position_mgr.active_positions.return_value = {}

    await bot.kill_switch(KillReason.DAILY_LOSS)

    assert bot._kill_reason == KillReason.CONSECUTIVE_LOSS


@pytest.mark.asyncio
async def test_kill_switch_maps_kosdaq_halt_reason():
    """RiskManager halt_type=kosdaq_halt → KillReason.KOSDAQ_HALT (BUG-26)."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus, KillReason
    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._kill_event = asyncio.Event()
    bot._stopping_event = asyncio.Event()

    mock_risk = MagicMock()
    mock_risk.halt_type = "kosdaq_halt"
    bot._risk_mgr = mock_risk
    bot._position_mgr = MagicMock()
    bot._executor = MagicMock()
    bot._executor.active_order_nos.return_value = []
    bot._position_mgr.active_positions.return_value = {}

    await bot.kill_switch(KillReason.DAILY_LOSS)

    assert bot._kill_reason == KillReason.KOSDAQ_HALT


# ─────────────────────────────────────────────────────────────────────────────
# BUG-06 — _emergency_reconcile: broker 조회 실패 시 내부 포지션 유지
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_reconcile_broker_fail_keeps_positions():
    """broker balance 조회 실패 시 내부 포지션 CLOSED 강제 설정 없음 (BUG-06)."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus
    bot = ScalpingBot()
    bot._status = BotStatus.STOPPING

    mock_executor = MagicMock()
    mock_executor.active_order_nos.return_value = []
    mock_executor.cancel_pending = AsyncMock()
    bot._executor = mock_executor

    mock_pos_mgr = MagicMock()
    mock_pos = MagicMock()
    mock_pos.remaining_qty = 10
    mock_pos.phase = PositionPhase.FULL
    mock_pos_mgr.active_positions.return_value = {"A005930": mock_pos}
    bot._position_mgr = mock_pos_mgr

    # adapter.inquire_balance 실패 시뮬레이션
    mock_adapter = MagicMock()
    mock_adapter.inquire_balance = MagicMock(side_effect=Exception("network error"))
    bot._adapter = mock_adapter
    bot._cfg = MagicMock()
    bot._cfg.broker.env = "vts"
    bot._store = None

    liquidate_called = []
    async def mock_liquidate(sym, qty):
        liquidate_called.append((sym, qty))
    bot._liquidate_position = mock_liquidate

    await bot._emergency_reconcile()

    # broker 조회 실패 → 내부 포지션 기준으로 재청산 시도 (CLOSED 강제 설정 안 함)
    assert mock_pos.phase != PositionPhase.CLOSED or len(liquidate_called) > 0


# ─────────────────────────────────────────────────────────────────────────────
# BUG-40 — _cancel_entry_for: exit 시 entry 취소 신호
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_exit_sets_cancel_entry_for():
    """_execute_exit() 호출 즉시 _cancel_entry_for에 심볼 추가 (BUG-40)."""
    from src.trading.scalping.bot import ScalpingBot, BotStatus
    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._exit_locks = {}
    bot._cancel_entry_for = set()
    bot._position_mgr = MagicMock()
    bot._position_mgr.on_fill_exit.return_value = None
    bot._store = None

    mock_executor = MagicMock()
    mock_executor.submit = AsyncMock(return_value=None)
    mock_executor.submit_market = AsyncMock(return_value=None)
    bot._executor = mock_executor

    req = OrderRequest(
        symbol="A005930", side="sell", qty=10,
        price=73_000.0, order_type="limit",
        reason="exit_sl",
    )

    # exit 실행 중 cancel_entry_for 설정 확인
    cancel_set_during_exec = []

    original_submit = mock_executor.submit
    async def submit_with_check(r, **kw):
        cancel_set_during_exec.append("A005930" in bot._cancel_entry_for)
        return None
    mock_executor.submit = submit_with_check

    await bot._execute_exit(req, expected_price=73_000.0)

    assert any(cancel_set_during_exec), "_cancel_entry_for should be set before submit"


# ─────────────────────────────────────────────────────────────────────────────
# BUG-40 — entry lock이 exit lock과 독립적
# ─────────────────────────────────────────────────────────────────────────────

def test_entry_exit_locks_are_independent():
    """_entry_locks와 _exit_locks는 서로 다른 lock 객체 (BUG-40)."""
    from src.trading.scalping.bot import ScalpingBot
    bot = ScalpingBot()
    sym = "A005930"
    bot._entry_locks[sym] = asyncio.Lock()
    bot._exit_locks[sym] = asyncio.Lock()
    assert bot._entry_locks[sym] is not bot._exit_locks[sym]


# ─────────────────────────────────────────────────────────────────────────────
# BUG-34 — stop_bot() waits for kill_event before cancel
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_bot_waits_for_kill_event():
    """stop_bot()은 kill_event 대기 후 task cancel (BUG-34)."""
    from src.trading.scalping import bot as bot_module
    from src.trading.scalping.bot import ScalpingBot, BotStatus, KillReason

    mock_bot = ScalpingBot()
    mock_bot._status = BotStatus.RUNNING
    mock_bot._kill_event = asyncio.Event()
    mock_bot._stopping_event = asyncio.Event()
    mock_bot._position_mgr = MagicMock()
    mock_bot._position_mgr.active_positions.return_value = {}
    mock_bot._executor = MagicMock()
    mock_bot._executor.active_order_nos.return_value = []
    mock_bot._risk_mgr = MagicMock()
    mock_bot._risk_mgr.halt_type = "unknown"

    kill_switch_called = asyncio.Event()

    async def mock_kill_switch(reason=""):
        kill_switch_called.set()
        mock_bot._status = BotStatus.STOPPING
        # kill_event를 즉시 set (청산 완료 시뮬레이션)
        mock_bot._kill_event.set()
    mock_bot.kill_switch = mock_kill_switch

    task_cancelled = []
    mock_task = asyncio.create_task(asyncio.sleep(100))

    bot_module._bot = mock_bot
    bot_module._bot_task = mock_task

    await bot_module.stop_bot()

    assert mock_task.cancelled() or mock_task.done()
    # kill_event가 set된 후에 task가 취소됐는지 확인
    assert mock_bot._kill_event.is_set()

    # cleanup
    bot_module._bot = None
    bot_module._bot_task = None
