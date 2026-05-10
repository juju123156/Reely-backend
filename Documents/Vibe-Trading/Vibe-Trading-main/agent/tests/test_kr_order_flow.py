"""Tests for kr_order_flow — 수급 신호 엔진."""

from __future__ import annotations

import pytest
from src.trading.kr_order_flow import OrderFlowState, OrderFlowBook


def _feed(state: OrderFlowState, price: float, buy: float, sell: float,
          bid: float = 0.0, ask: float = 0.0) -> None:
    state.update_poll(
        price=price,
        buy_vol_total=buy,
        sell_vol_total=sell,
        bid_qty=bid,
        ask_qty=ask,
    )


# ------------------------------------------------------------------
# 체결강도
# ------------------------------------------------------------------

def test_exec_strength_neutral_on_empty():
    s = OrderFlowState()
    assert s.exec_strength() == 100.0


def test_exec_strength_strong_buy():
    s = OrderFlowState(window=5)
    for i in range(5):
        _feed(s, 10000, buy=150 * (i + 1), sell=100 * (i + 1))
    assert s.exec_strength() > 130.0


def test_exec_strength_strong_sell():
    s = OrderFlowState(window=5)
    for i in range(5):
        _feed(s, 10000, buy=60 * (i + 1), sell=100 * (i + 1))
    assert s.exec_strength() < 70.0


# ------------------------------------------------------------------
# 호가잔량비
# ------------------------------------------------------------------

def test_ob_imbalance_neutral_on_zero_ask():
    s = OrderFlowState()
    assert s.ob_imbalance() == 1.0


def test_ob_imbalance_bid_heavy():
    s = OrderFlowState()
    _feed(s, 10000, 100, 100, bid=1500, ask=1000)
    assert s.ob_imbalance() == pytest.approx(1.5)


def test_ob_imbalance_ask_heavy():
    s = OrderFlowState()
    _feed(s, 10000, 100, 100, bid=600, ask=1000)
    assert s.ob_imbalance() == pytest.approx(0.6)


# ------------------------------------------------------------------
# 누적 → 델타 변환
# ------------------------------------------------------------------

def test_delta_conversion():
    """KIS는 누적값을 주므로 델타가 올바르게 계산되는지 확인."""
    s = OrderFlowState(window=10)
    _feed(s, 10000, buy=1000, sell=800)   # 1번째 폴: delta = 1000, 800
    _feed(s, 10001, buy=1300, sell=1000)  # 2번째 폴: delta = 300, 200
    # 윈도우 내 buy_sum = 1000 + 300 = 1300
    # sell_sum = 800 + 200 = 1000
    assert s._buy_sum == pytest.approx(1300.0)
    assert s._sell_sum == pytest.approx(1000.0)


# ------------------------------------------------------------------
# 추매 신호
# ------------------------------------------------------------------

def test_pyramid_signal_when_all_conditions_met():
    s = OrderFlowState(
        pyramid_es_min=130.0,
        pyramid_ob_min=1.5,
        pyramid_vol_min=1.5,
        pyramid_pnl_min=0.005,
    )
    s.set_baseline()
    s._baseline_vol = 100.0  # 기준 거래량 강제 설정

    # 체결강도 > 130, 호가잔량비 > 1.5, 거래량 > 150
    _feed(s, 10000, buy=1300, sell=1000, bid=1500, ask=1000)
    _feed(s, 10050, buy=2700, sell=2000, bid=1500, ask=1000)
    s._buy_vols[-1] = 200.0   # vol_ratio = 200/100 = 2.0
    s._sell_vols[-1] = 50.0

    sig = s.evaluate(in_position=True, unrealized_pnl=0.01)
    assert sig.action == "pyramid"


def test_no_pyramid_without_position():
    s = OrderFlowState()
    _feed(s, 10000, buy=1300, sell=1000, bid=1500, ask=1000)
    sig = s.evaluate(in_position=False)
    assert sig.action == "hold"


def test_no_pyramid_when_pnl_too_low():
    s = OrderFlowState(pyramid_pnl_min=0.005)
    s._baseline_vol = 100.0
    _feed(s, 10000, buy=1300, sell=1000, bid=1500, ask=1000)
    sig = s.evaluate(in_position=True, unrealized_pnl=0.001)  # 0.1% < 0.5%
    assert sig.action != "pyramid"


# ------------------------------------------------------------------
# 매도 신호
# ------------------------------------------------------------------

def test_exit_on_low_exec_strength():
    s = OrderFlowState(exit_es_max=70.0)
    for i in range(5):
        _feed(s, 10000, buy=60 * (i + 1), sell=100 * (i + 1))
    sig = s.evaluate(in_position=True)
    assert sig.action == "exit"
    assert "체결강도" in sig.reason


def test_exit_on_low_ob_imbalance():
    s = OrderFlowState(exit_ob_max=0.7)
    _feed(s, 10000, 100, 100, bid=600, ask=1000)
    sig = s.evaluate(in_position=True)
    assert sig.action == "exit"
    assert "호가" in sig.reason


def test_exit_on_climax_exhaustion():
    s = OrderFlowState(exit_vol_climax=3.0, exit_es_max=70.0, exit_ob_max=0.7)
    s._baseline_vol = 100.0
    s._session_high = 10100.0  # 이미 더 높은 고점이 있음

    # 거래량 폭증이지만 고점 미갱신
    _feed(s, 10050, buy=300, sell=100, bid=1000, ask=500)
    s._buy_vols[-1] = 350.0  # vol_ratio = 350/100 = 3.5 > 3.0
    s._sell_vols[-1] = 0.0

    sig = s.evaluate(in_position=True)
    assert sig.action == "exit"
    assert "클라이맥스" in sig.reason


# ------------------------------------------------------------------
# OrderFlowBook
# ------------------------------------------------------------------

def test_book_creates_states_per_symbol():
    book = OrderFlowBook(window=10)
    s1 = book.get_or_create("005930")
    s2 = book.get_or_create("000660")
    s1_again = book.get_or_create("005930")
    assert s1 is s1_again
    assert s1 is not s2


def test_book_remove():
    book = OrderFlowBook()
    book.get_or_create("005930")
    book.remove("005930")
    assert "005930" not in book.symbols()


# ------------------------------------------------------------------
# 링버퍼 윈도우 경계
# ------------------------------------------------------------------

def test_ring_buffer_eviction():
    """윈도우 크기를 넘으면 오래된 값이 올바르게 제거되는지 확인."""
    s = OrderFlowState(window=3)
    _feed(s, 100, buy=1000, sell=1000)  # delta 1000, 1000
    _feed(s, 101, buy=2000, sell=2000)  # delta 1000, 1000
    _feed(s, 102, buy=3000, sell=3000)  # delta 1000, 1000  (버퍼 꽉 참)
    _feed(s, 103, buy=4300, sell=4300)  # delta 1300, 1300  (첫 번째 1000 제거)

    # buy_sum = 1000 + 1000 + 1300 = 3300
    assert s._buy_sum == pytest.approx(3300.0)
