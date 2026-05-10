"""KRX 시장 규정 적합성 테스트 — 호가단위, 시간 규칙, 필터 강화."""

from __future__ import annotations

import asyncio
from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.scalping.constants import (
    FORCE_CLOSE_TIME, SOFT_CLOSE_TIME, CLOSING_AUCTION_START, NO_ORDER_AFTER,
    NO_ENTRY_UNTIL, CONSERVATIVE_ENTRY_UNTIL, CONSERVATIVE_SCORE_BOOST,
    MAX_OPEN_GAP_PCT, MAX_CHANGE_NEAR_LIMIT,
    CIRCUIT_BREAKER_THRESHOLD,
    MIN_PROFIT_COST_RATIO,
)
from src.trading.scalping.kr_market_utils import get_tick_size, round_to_tick, calc_round_trip_cost
from src.trading.scalping.market_scanner import SymbolCandidate, MarketScanner
from src.trading.scalping.signal_engine import SignalEngine, SymbolState
from src.trading.scalping.events import TickEvent, OrderRequest


# ─── 1. 시간 상수 순서 검증 ──────────────────────────────────────────────────

def test_time_order():
    """시간 상수 순서: SOFT_CLOSE < FORCE_CLOSE < NO_ORDER_AFTER < CLOSING_AUCTION."""
    assert SOFT_CLOSE_TIME < FORCE_CLOSE_TIME
    assert FORCE_CLOSE_TIME < NO_ORDER_AFTER
    assert NO_ORDER_AFTER < CLOSING_AUCTION_START   # 주문 금지는 동시호가 시작 전
    assert NO_ENTRY_UNTIL < CONSERVATIVE_ENTRY_UNTIL


def test_force_close_time_is_1510():
    assert FORCE_CLOSE_TIME == time(15, 10)


def test_closing_auction_start_is_1520():
    assert CLOSING_AUCTION_START == time(15, 20)


def test_no_order_after_before_auction():
    """NO_ORDER_AFTER(15:19:30)는 CLOSING_AUCTION_START(15:20:00) 직전이어야 한다."""
    assert NO_ORDER_AFTER < CLOSING_AUCTION_START
    assert NO_ORDER_AFTER == time(15, 19, 30)


# ─── 2. KRX 호가단위 (tick size) ─────────────────────────────────────────────

@pytest.mark.parametrize("price,market,expected_tick", [
    # KOSDAQ
    (999,     "KOSDAQ",  1),
    (1_000,   "KOSDAQ",  5),
    (4_999,   "KOSDAQ",  5),
    (5_000,   "KOSDAQ", 10),
    (9_999,   "KOSDAQ", 10),
    (10_000,  "KOSDAQ", 50),
    (49_999,  "KOSDAQ", 50),
    (50_000,  "KOSDAQ", 100),
    (99_999,  "KOSDAQ", 100),
    (100_000, "KOSDAQ", 500),
    (499_999, "KOSDAQ", 500),
    (500_000, "KOSDAQ", 1_000),
    # KOSPI
    (1_999,   "KOSPI",   1),
    (2_000,   "KOSPI",   5),
    (19_999,  "KOSPI",  10),
    (20_000,  "KOSPI",  50),
    (199_999, "KOSPI", 100),
    (200_000, "KOSPI", 500),
    (500_000, "KOSPI", 1_000),
])
def test_get_tick_size(price, market, expected_tick):
    assert get_tick_size(price, market) == expected_tick


@pytest.mark.parametrize("price,market,mode,expected", [
    (10_050, "KOSDAQ", "down", 10_050),   # already on tick
    (10_030, "KOSDAQ", "down", 10_000),   # buy: round down
    (10_030, "KOSDAQ", "up",   10_050),   # sell: round up
    (5_007,  "KOSDAQ", "down", 5_000),
    (5_007,  "KOSDAQ", "up",   5_010),
    (0,      "KOSDAQ", "down", 0),        # edge: zero price
])
def test_round_to_tick(price, market, mode, expected):
    assert round_to_tick(price, market, mode) == expected


def test_round_trip_cost_kosdaq_vs_kospi():
    """KOSDAQ 거래세(0.18%)가 KOSPI(0.03%)보다 크다."""
    cost_kosdaq = calc_round_trip_cost(10_000, "KOSDAQ")
    cost_kospi  = calc_round_trip_cost(10_000, "KOSPI")
    assert cost_kosdaq > cost_kospi


# ─── 3. 종목 필터 — 신규 제외 조건 ──────────────────────────────────────────

def _make_candidate(**kwargs) -> SymbolCandidate:
    defaults = dict(
        symbol="000660", name="SK하이닉스", price=100_000,
        change_pct=0.05, trading_value=10_000_000_000,
        volume=500_000, exec_strength=160.0,
    )
    defaults.update(kwargs)
    return SymbolCandidate(**defaults)


def _make_scanner() -> MarketScanner:
    adapter = MagicMock()
    return MarketScanner(adapter)


def test_filter_passes_normal():
    scanner = _make_scanner()
    c = _make_candidate()
    assert scanner._passes_filter(c) is True


def test_filter_blocks_investment_caution():
    scanner = _make_scanner()
    c = _make_candidate(is_investment_caution=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_investment_warning():
    scanner = _make_scanner()
    c = _make_candidate(is_investment_warning=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_investment_danger():
    scanner = _make_scanner()
    c = _make_candidate(is_investment_danger=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_short_term_overheated():
    scanner = _make_scanner()
    c = _make_candidate(is_short_term_overheated=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_trading_halted():
    scanner = _make_scanner()
    c = _make_candidate(is_trading_halted=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_etf():
    scanner = _make_scanner()
    c = _make_candidate(is_etf=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_etn():
    scanner = _make_scanner()
    c = _make_candidate(is_etn=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_spac():
    scanner = _make_scanner()
    c = _make_candidate(is_spac=True)
    assert scanner._passes_filter(c) is False


def test_filter_blocks_gap_up_via_open_gap_pct():
    """open_gap_pct >= MAX_OPEN_GAP_PCT → 제외."""
    scanner = _make_scanner()
    c = _make_candidate(open_gap_pct=MAX_OPEN_GAP_PCT, change_pct=0.04)
    assert scanner._passes_filter(c) is False


def test_filter_allows_gap_up_without_open_gap_data():
    """open_gap_pct 데이터 없으면(=0) 갭업 필터 미적용 — change_pct만으로는 판단 불가."""
    scanner = _make_scanner()
    c = _make_candidate(open_gap_pct=0.0, change_pct=0.05)
    assert scanner._passes_filter(c) is True


def test_filter_blocks_near_limit():
    """change_pct >= MAX_CHANGE_NEAR_LIMIT(0.20) → 상한가 근접 제외."""
    scanner = _make_scanner()
    c = _make_candidate(change_pct=MAX_CHANGE_NEAR_LIMIT)
    assert scanner._passes_filter(c) is False


# ─── 4. 장 초반 진입 금지 ────────────────────────────────────────────────────

def test_no_entry_until_constant():
    assert NO_ENTRY_UNTIL == time(9, 5)


def test_conservative_entry_until_constant():
    assert CONSERVATIVE_ENTRY_UNTIL == time(9, 10)


def test_conservative_score_boost_positive():
    assert CONSERVATIVE_SCORE_BOOST > 0


# ─── 5. VI 해제 후 PullbackTracker 리셋 ──────────────────────────────────────

def test_vi_release_resets_pullback():
    """VI 쿨다운 만료 틱에서 PullbackTracker가 reset + register_high 호출된다."""
    engine = SignalEngine()
    st = engine.register("000660")

    # 고점 + 눌림 상태 만들기
    import time as _t
    st.pullback.register_high(10_000, _t.time() - 1)
    st.pullback.update(9_800, _t.time(), 900)
    assert st.pullback.phase == "pullback"

    # VI 감지 → 쿨다운 이미 만료된 상태 시뮬레이션
    from src.trading.scalping.constants import VI_COOLDOWN_SECS
    st.vi_detected_at = _t.time() - VI_COOLDOWN_SECS - 1  # 만료됨

    tick = TickEvent(
        symbol="000660", price=10_100,
        buy_vol_total=1000, sell_vol_total=500,
        bid_qty=200, ask_qty=100,
        tick_vol=50, acml_vol=100_000, acml_tr_pbmn=1_000_000_000,
        time_str="091500", is_vi=False,
    )
    engine.process_tick(tick)

    # 쿨다운 만료 → vi_detected_at 초기화, pullback 리셋 후 watching 상태
    assert st.vi_detected_at == 0.0
    assert st.pullback.phase in ("watching", "idle")


# ─── 6. 서킷브레이커 임계값 ──────────────────────────────────────────────────

def test_circuit_breaker_threshold():
    assert CIRCUIT_BREAKER_THRESHOLD == -0.08


# ─── 7. 슬리피지 포함 기대수익 비율 ─────────────────────────────────────────

def test_min_profit_cost_ratio():
    assert MIN_PROFIT_COST_RATIO >= 2.0
