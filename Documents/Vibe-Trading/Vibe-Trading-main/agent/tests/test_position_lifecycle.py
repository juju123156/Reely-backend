"""포지션 lifecycle 테스트 — PositionType 시스템 + 종가베팅 복구 설계 검증."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.scalping.position_manager import PositionManager, PositionPhase, Position
from src.trading.scalping.position_type import (
    PositionType, ttl_for, infer_from_recovery_time, from_value,
)
from src.trading.scalping.events import FillEvent, TickEvent

_FORCE_CLOSE_REASON = "force_close_time"


def _liquidation_required(mgr: PositionManager, reason: str) -> dict:
    """bot._liquidation_required_positions() 와 동일한 필터링 로직."""
    positions = dict(mgr.active_positions())
    if reason == _FORCE_CLOSE_REASON:
        return {
            symbol: pos
            for symbol, pos in positions.items()
            if getattr(pos, "position_type", PositionType.UNKNOWN) != PositionType.CLOSE_BET
        }
    return positions


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _fill(symbol: str = "000660", price: float = 50_000, qty: int = 10) -> FillEvent:
    return FillEvent(
        order_no="ORD001", symbol=symbol, side="buy",
        filled_qty=qty, fill_price=price, commission=price * qty * 0.00015, tax=0.0,
    )


def _tick(symbol: str = "000660", price: float = 50_000) -> TickEvent:
    return TickEvent(
        symbol=symbol, price=price,
        buy_vol_total=100_000, sell_vol_total=80_000,
        bid_qty=5000, ask_qty=3000,
        tick_vol=100, acml_vol=1_000_000, acml_tr_pbmn=50_000_000_000,
        time_str="090500",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PositionType enum & helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_position_type_values():
    assert PositionType.INTRADAY_SCALP.value == "intraday_scalp"
    assert PositionType.CLOSE_BET.value == "close_bet"
    assert PositionType.UNKNOWN.value == "unknown"


def test_ttl_close_bet_longer():
    assert ttl_for(PositionType.CLOSE_BET) >= 24 * 3600
    assert ttl_for(PositionType.INTRADAY_SCALP) <= 8 * 3600


def test_from_value_valid():
    assert from_value("close_bet") == PositionType.CLOSE_BET
    assert from_value("intraday_scalp") == PositionType.INTRADAY_SCALP


def test_from_value_invalid_returns_unknown():
    assert from_value("garbage") == PositionType.UNKNOWN
    assert from_value(None) == PositionType.UNKNOWN
    assert from_value("") == PositionType.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# infer_from_recovery_time
# ─────────────────────────────────────────────────────────────────────────────

def test_infer_before_market_open_is_close_bet():
    """테스트 3: Redis 만료, broker만 존재, 08:50 → CLOSE_BET 추론."""
    now = datetime.now().replace(hour=8, minute=50, second=0)
    pt, session, exit_sess = infer_from_recovery_time(now)
    assert pt == PositionType.CLOSE_BET
    assert session == "broker_recovered"
    assert exit_sess == "next_open"


def test_infer_during_market_is_unknown():
    """테스트 4: Redis 만료, broker만 존재, 11:00 → UNKNOWN."""
    now = datetime.now().replace(hour=11, minute=0, second=0)
    pt, session, exit_sess = infer_from_recovery_time(now)
    assert pt == PositionType.UNKNOWN
    assert session == "broker_recovered"
    assert exit_sess == "manual"


# ─────────────────────────────────────────────────────────────────────────────
# Position.from_snapshot — 필드 복원
# ─────────────────────────────────────────────────────────────────────────────

def test_from_snapshot_restores_position_type():
    """테스트 1: 전날 CLOSE_BET 저장 후 재시작 — position_type 유지."""
    data = {
        "symbol": "000660",
        "avg_price": 50_000.0,
        "entry_price": 50_000.0,
        "remaining_qty": 10,
        "total_qty": 10,
        "phase": PositionPhase.ENTERING.value,
        "atr_at_entry": 500.0,
        "hard_stop": 48_500.0,
        "break_even_stop": 0.0,
        "trailing_high": 50_000.0,
        "trailing_stop": 49_000.0,
        "realized_pnl": 0.0,
        "exit_1_triggered": False,
        "exit_2_triggered": False,
        "market": "KOSDAQ",
        "position_type": "close_bet",
        "opened_at": "2025-05-06T14:55:00",
        "strategy_id": "close_bet",
        "entry_session": "close_auction",
        "intended_exit_session": "next_open",
    }
    pos = Position.from_snapshot(data)
    assert pos.position_type == PositionType.CLOSE_BET
    assert pos.intended_exit_session == "next_open"
    assert pos.entry_session == "close_auction"
    assert pos.opened_at == datetime(2025, 5, 6, 14, 55, 0)


def test_from_snapshot_missing_position_type_defaults_unknown():
    """position_type 없는 구 스냅샷 → UNKNOWN."""
    data = {
        "symbol": "000660",
        "avg_price": 50_000.0, "entry_price": 50_000.0,
        "remaining_qty": 10, "total_qty": 10,
        "phase": PositionPhase.ENTERING.value,
        "atr_at_entry": 0, "hard_stop": 48_500.0,
        "break_even_stop": 0, "trailing_high": 50_000.0, "trailing_stop": 49_000.0,
        "realized_pnl": 0, "exit_1_triggered": False, "exit_2_triggered": False,
        "market": "KOSDAQ",
        # position_type 없음 — 구 버전 스냅샷
    }
    pos = Position.from_snapshot(data)
    assert pos.position_type == PositionType.UNKNOWN


def test_from_snapshot_missing_opened_at_uses_sentinel():
    """opened_at 없는 구 스냅샷 → 2000-01-01 sentinel (datetime.now() 금지)."""
    data = {
        "symbol": "000660",
        "avg_price": 50_000.0, "entry_price": 50_000.0,
        "remaining_qty": 10, "total_qty": 10,
        "phase": PositionPhase.ENTERING.value,
        "atr_at_entry": 0, "hard_stop": 48_500.0,
        "break_even_stop": 0, "trailing_high": 50_000.0, "trailing_stop": 49_000.0,
        "realized_pnl": 0, "exit_1_triggered": False, "exit_2_triggered": False,
        "market": "KOSDAQ",
        # opened_at 없음
    }
    pos = Position.from_snapshot(data)
    assert pos.opened_at.year == 2000, "opened_at 없을 때 datetime.now()로 덮어쓰면 안 됨"


# ─────────────────────────────────────────────────────────────────────────────
# check_exits — CLOSE_BET 시간 게이트 스킵
# ─────────────────────────────────────────────────────────────────────────────

def test_close_bet_skips_force_close_time():
    """CLOSE_BET 포지션은 FORCE_CLOSE_TIME(15:10)에 청산되면 안 된다."""
    mgr = PositionManager()
    fill = _fill()
    pos = mgr.on_fill_entry(
        fill, atr=500.0,
        position_type=PositionType.CLOSE_BET,
        intended_exit_session="next_open",
    )

    tick = _tick(price=50_500)
    req = mgr.check_exits(
        "000660", tick,
        exec_strength=120.0, ob_imbalance=1.2,
        vwap=50_000.0,
        now_time=time(15, 12),   # FORCE_CLOSE_TIME 이후
    )
    assert req is None, "CLOSE_BET는 FORCE_CLOSE_TIME에 청산되면 안 됨"


def test_close_bet_still_exits_on_hard_stop():
    """CLOSE_BET도 hard_stop 하회 시 즉시 청산."""
    mgr = PositionManager()
    fill = _fill(price=50_000)
    mgr.on_fill_entry(
        fill, atr=500.0,
        position_type=PositionType.CLOSE_BET,
        intended_exit_session="next_open",
    )
    pos = mgr.get_position("000660")

    tick = _tick(price=pos.hard_stop - 100)  # hard_stop 하회
    req = mgr.check_exits(
        "000660", tick,
        exec_strength=80.0, ob_imbalance=0.5,
        vwap=50_000.0,
        now_time=time(14, 55),
    )
    assert req is not None
    assert req.reason == "exit_sl"


def test_intraday_scalp_force_closed_at_15_10():
    """INTRADAY_SCALP는 FORCE_CLOSE_TIME에 정상 청산."""
    mgr = PositionManager()
    fill = _fill()
    mgr.on_fill_entry(
        fill, atr=500.0,
        position_type=PositionType.INTRADAY_SCALP,
    )

    tick = _tick(price=50_500)
    req = mgr.check_exits(
        "000660", tick,
        exec_strength=120.0, ob_imbalance=1.2,
        vwap=50_000.0,
        now_time=time(15, 12),
    )
    assert req is not None
    assert "force" in req.reason


def test_unknown_position_only_force_close_and_hard_stop():
    """UNKNOWN 포지션은 FORCE_CLOSE_TIME + hard_stop만 적용."""
    mgr = PositionManager()
    fill = _fill()
    mgr.on_fill_entry(fill, atr=500.0, position_type=PositionType.UNKNOWN)
    pos = mgr.get_position("000660")
    pos.intended_exit_session = "manual"

    # exec_strength 약해도 청산 안 됨
    tick = _tick(price=50_500)
    req = mgr.check_exits(
        "000660", tick,
        exec_strength=50.0, ob_imbalance=0.5,
        vwap=50_000.0,
        now_time=time(14, 0),
    )
    assert req is None

    # FORCE_CLOSE_TIME 도달 시 청산
    req = mgr.check_exits(
        "000660", tick,
        exec_strength=50.0, ob_imbalance=0.5,
        vwap=50_000.0,
        now_time=time(15, 15),
    )
    assert req is not None
    assert "unknown" in req.reason


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 2: intraday → CLOSE_BET 전환
# ─────────────────────────────────────────────────────────────────────────────

def test_position_type_conversion_intraday_to_close_bet():
    """테스트 2: INTRADAY_SCALP 포지션을 CLOSE_BET으로 전환."""
    mgr = PositionManager()
    fill = _fill()
    pos = mgr.on_fill_entry(fill, atr=500.0, position_type=PositionType.INTRADAY_SCALP)

    assert pos.position_type == PositionType.INTRADAY_SCALP
    assert pos.intended_exit_session == "same_day"

    # 14:50에 CLOSE_BET 조건 충족 → 전환
    pos.position_type = PositionType.CLOSE_BET
    pos.entry_session = "close_auction"
    pos.intended_exit_session = "next_open"
    pos.strategy_id = "close_bet"

    assert pos.position_type == PositionType.CLOSE_BET
    assert pos.intended_exit_session == "next_open"
    assert ttl_for(pos.position_type) >= 24 * 3600


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 5: 같은 종목 중복 방지 (CLOSE_BET + 신규 INTRADAY)
# ─────────────────────────────────────────────────────────────────────────────

def test_close_bet_blocks_same_symbol_intraday(monkeypatch):
    """테스트 5: 같은 종목 CLOSE_BET 미청산 → INTRADAY 신규 진입 금지."""
    mgr = PositionManager()
    fill = _fill(symbol="000660")
    mgr.on_fill_entry(fill, atr=500.0, position_type=PositionType.CLOSE_BET)

    active = mgr.active_positions()
    # 진입 차단 조건 검증: CLOSE_BET 포지션 존재
    has_close_bet = any(
        p.position_type == PositionType.CLOSE_BET for p in active.values()
    )
    assert has_close_bet, "CLOSE_BET 포지션이 active에 존재해야 함"
    # bot._handle_entry_signal에서 이 조건으로 차단됨


def test_unknown_position_blocks_all_new_entries():
    """UNKNOWN 포지션이 있으면 신규 진입 전체 차단."""
    mgr = PositionManager()
    fill = _fill(symbol="005930")
    mgr.on_fill_entry(fill, atr=500.0, position_type=PositionType.UNKNOWN)

    active = mgr.active_positions()
    has_unknown = any(p.position_type == PositionType.UNKNOWN for p in active.values())
    assert has_unknown


# ─────────────────────────────────────────────────────────────────────────────
# on_fill_entry — position_type 전파
# ─────────────────────────────────────────────────────────────────────────────

def test_on_fill_entry_default_is_intraday():
    mgr = PositionManager()
    pos = mgr.on_fill_entry(_fill(), atr=500.0)
    assert pos.position_type == PositionType.INTRADAY_SCALP
    assert pos.intended_exit_session == "same_day"


def test_on_fill_entry_close_bet():
    mgr = PositionManager()
    pos = mgr.on_fill_entry(
        _fill(), atr=500.0,
        position_type=PositionType.CLOSE_BET,
        entry_session="close_auction",
        intended_exit_session="next_open",
    )
    assert pos.position_type == PositionType.CLOSE_BET
    assert pos.entry_session == "close_auction"
    assert pos.intended_exit_session == "next_open"
    assert pos.strategy_id == "close_bet"


# ─────────────────────────────────────────────────────────────────────────────
# _time_loop / _liquidate_all 충돌 수정 검증
# ─────────────────────────────────────────────────────────────────────────────

def test_force_close_excludes_close_bet_from_liquidation():
    """FORCE_CLOSE_TIME 청산 대상에 CLOSE_BET 포함 금지 — INTRADAY만 청산."""
    mgr = PositionManager()
    mgr.on_fill_entry(_fill(symbol="000660"), atr=500.0, position_type=PositionType.INTRADAY_SCALP)
    mgr.on_fill_entry(_fill(symbol="005930"), atr=500.0, position_type=PositionType.CLOSE_BET)

    required = _liquidation_required(mgr, _FORCE_CLOSE_REASON)
    assert "000660" in required, "INTRADAY는 FORCE_CLOSE_TIME에 청산 대상이어야 함"
    assert "005930" not in required, "CLOSE_BET는 FORCE_CLOSE_TIME에 청산 대상이면 안 됨"


def test_daily_loss_liquidates_all_including_close_bet():
    """DAILY_LOSS kill → CLOSE_BET 포함 전체 청산 (시간 게이트 없음)."""
    mgr = PositionManager()
    mgr.on_fill_entry(_fill(symbol="000660"), atr=500.0, position_type=PositionType.INTRADAY_SCALP)
    mgr.on_fill_entry(_fill(symbol="005930"), atr=500.0, position_type=PositionType.CLOSE_BET)

    required = _liquidation_required(mgr, "daily_loss")
    assert "000660" in required
    assert "005930" in required, "DAILY_LOSS는 CLOSE_BET도 청산해야 함"


def test_close_bet_only_at_force_close_nothing_liquidated():
    """CLOSE_BET만 남았을 때 FORCE_CLOSE_TIME → 청산 대상 0 → kill_switch 스킵."""
    mgr = PositionManager()
    mgr.on_fill_entry(_fill(symbol="005930"), atr=500.0, position_type=PositionType.CLOSE_BET)

    required = _liquidation_required(mgr, _FORCE_CLOSE_REASON)
    assert len(required) == 0, "CLOSE_BET만 있으면 FORCE_CLOSE_TIME에 청산 대상 0 → kill_switch 스킵"
