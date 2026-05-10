"""Tests for scalping core: vwap, signal_engine, position_manager, risk_manager."""

from __future__ import annotations

import time
from datetime import datetime, time as dtime

import pytest

from src.trading.scalping.vwap import VWAPState, ATRState, PullbackTracker, Candle
from src.trading.scalping.signal_engine import SignalEngine, EntryScore
from src.trading.scalping.position_manager import PositionManager, PositionPhase
from src.trading.scalping.risk_manager import RiskManager
from src.trading.scalping.events import TickEvent, FillEvent


# ─────────────────────────────────────────────────────────────────────────────
# VWAPState
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_acml_update():
    v = VWAPState()
    v.update_acml(acml_tr_pbmn=72_000 * 1000, acml_vol=1000)
    assert v.vwap == pytest.approx(72_000, rel=1e-4)


def test_vwap_tick_update():
    v = VWAPState()
    v.update_tick(price=72_000, volume=100)
    v.update_tick(price=73_000, volume=100)
    assert v.vwap == pytest.approx(72_500, rel=1e-4)


def test_vwap_gap_above():
    v = VWAPState()
    v.update_acml(72_000 * 1000, 1000)
    gap = v.gap(73_000)
    assert gap == pytest.approx(1 / 72, rel=1e-3)


def test_vwap_gap_below_zero():
    v = VWAPState()
    v.update_acml(72_000 * 1000, 1000)
    assert v.gap(71_000) < 0


def test_vwap_zero_volume_returns_zero():
    v = VWAPState()
    assert v.vwap == 0.0
    assert v.gap(72_000) == 0.0


def test_vwap_reset():
    v = VWAPState()
    v.update_tick(72_000, 100)
    v.reset()
    assert v.vwap == 0.0


def test_vwap_warmup():
    v = VWAPState()
    assert not v.is_warmed_up
    for _ in range(120):
        v.update_tick(72_000, 1)
    assert v.is_warmed_up


# ─────────────────────────────────────────────────────────────────────────────
# ATRState
# ─────────────────────────────────────────────────────────────────────────────

def _make_candles(n: int, high=500, low=400, close=450) -> list[Candle]:
    return [Candle(high=high, low=low, close=close) for _ in range(n)]


def test_atr_not_ready_before_period():
    a = ATRState(period=14)
    for c in _make_candles(13):
        a.update_candle(c.high, c.low, c.close)
    assert not a.ready


def test_atr_ready_after_period():
    a = ATRState(period=14)
    a.bulk_load(_make_candles(14))
    assert a.ready
    assert a.atr > 0


def test_atr_wilder_smoothing():
    a = ATRState(period=3)
    a.update_candle(110, 90, 100)   # TR=20, prev_close=0 → TR=high-low
    a.update_candle(115, 95, 105)   # TR=max(20, 15, 5)=20
    a.update_candle(120, 100, 110)  # TR=max(20, 15, 5)=20
    assert a.ready
    assert a.atr == pytest.approx(20.0, rel=0.01)


def test_atr_bulk_load():
    a = ATRState(period=5)
    a.bulk_load(_make_candles(10, high=200, low=100, close=150))
    assert a.ready


# ─────────────────────────────────────────────────────────────────────────────
# PullbackTracker
# ─────────────────────────────────────────────────────────────────────────────

def _tracker() -> PullbackTracker:
    return PullbackTracker("005930")


def test_pullback_idle_by_default():
    t = _tracker()
    assert t.phase == "idle"


def test_pullback_watching_after_register():
    t = _tracker()
    t.register_high(72_000, time.time())
    assert t.phase == "watching"


def test_pullback_detected():
    t = _tracker()
    t.register_high(72_000, time.time())
    phase = t.update(70_560, time.time(), 900)  # -2.0% → 유효 눌림
    assert phase == "pullback"


def test_pullback_too_deep_resets():
    t = _tracker()
    t.register_high(72_000, time.time())
    phase = t.update(69_800, time.time(), 900)  # -3.1% → 과다
    assert phase == "idle"


def test_pullback_breakout():
    t = _tracker()
    ts = time.time()
    t.register_high(72_000, ts)
    t.update(71_000, ts + 10, 900)            # pullback
    phase1 = t.update(72_100, ts + 20, 900)   # 첫 번째 돌파 틱 (BREAKOUT_CONFIRM_TICKS=2)
    assert phase1 == "pullback"                # 아직 1틱 — 확정 전
    phase2 = t.update(72_200, ts + 21, 900)   # 두 번째 돌파 틱 → 확정
    assert phase2 == "breakout"


def test_pullback_breakout_count_resets_on_dip():
    """돌파 카운팅 중 가격이 고점 아래로 내려오면 카운트 초기화."""
    t = _tracker()
    ts = time.time()
    t.register_high(72_000, ts)
    t.update(71_000, ts + 10, 900)             # pullback
    t.update(72_100, ts + 20, 900)             # 1틱 돌파
    phase = t.update(71_900, ts + 21, 900)     # 고점 아래 → 카운트 0으로 리셋
    assert phase == "pullback"
    assert t._breakout_confirm_count == 0


def test_pullback_breakout_persists():
    """breakout 확정 후에도 계속 breakout 반환."""
    t = _tracker()
    ts = time.time()
    t.register_high(72_000, ts)
    t.update(71_000, ts + 10, 900)
    t.update(72_100, ts + 20, 900)
    t.update(72_200, ts + 21, 900)   # 확정
    phase = t.update(72_300, ts + 22, 900)   # 이후 틱도 breakout
    assert phase == "breakout"


def test_pullback_timeout():
    t = _tracker()
    t.register_high(72_000, 0.0)
    phase = t.update(71_500, 1000.0, 900)  # 1000초 경과 → timeout
    assert phase == "idle"


# ─────────────────────────────────────────────────────────────────────────────
# SignalEngine
# ─────────────────────────────────────────────────────────────────────────────

def _tick(symbol="005930", price=72_000, es=160.0, bid=2000.0, ask=1000.0,
          buy_vol=6000.0, sell_vol=4000.0, acml_vol=0.0, acml_pbmn=0.0) -> TickEvent:
    return TickEvent(
        symbol=symbol, price=price,
        buy_vol_total=buy_vol, sell_vol_total=sell_vol,
        bid_qty=bid, ask_qty=ask,
        tick_vol=100, acml_vol=acml_vol, acml_tr_pbmn=acml_pbmn,
        time_str="100000",
    )


def test_signal_engine_no_signal_without_register():
    eng = SignalEngine()
    result = eng.process_tick(_tick())
    assert result is None


def test_signal_engine_no_signal_without_breakout():
    eng = SignalEngine()
    eng.register("005930")
    result = eng.process_tick(_tick())
    # 눌림 미등록 → breakout 아님 → None
    assert result is None or result.action != "enter_now"


def test_signal_engine_exit_signal_weak_exec_strength():
    eng = SignalEngine()
    eng.register("005930")
    tick = _tick(es=60.0, buy_vol=3000.0, sell_vol=7000.0)
    result = eng.process_tick(tick)
    assert result is not None
    assert result.action == "exit"


def test_signal_engine_vi_suppresses_signal():
    eng = SignalEngine()
    eng.register("005930")
    tick = _tick()
    tick.is_vi = True
    result = eng.process_tick(tick)
    assert result is None


def test_signal_engine_score_components_sum():
    eng = SignalEngine()
    eng.register("005930")
    eng.inject_vol_ratio("005930", 5.0)
    eng._states["005930"].vwap.update_acml(72_000 * 1000, 1000)
    # ATR 주입
    eng.inject_atr_candles("005930", _make_candles(14, high=73000, low=71000, close=72000))

    # 직접 점수 계산
    st = eng._states["005930"]
    tick = _tick(price=72_500, buy_vol=6000, sell_vol=4000, bid=3000, ask=1000)
    score = eng._compute_score(st, tick, market_strength=0.8)

    assert 0 <= score.total <= 100
    # 각 컴포넌트 합 == total
    component_sum = (
        score.exec_strength_score + score.vol_ratio_score + score.vwap_gap_score
        + score.ob_imbalance_score + score.market_strength_score + score.volatility_score
    )
    assert abs(score.total - component_sum) < 0.1


def test_signal_engine_score_formula_max():
    """최적 조건에서 각 컴포넌트가 상한(가중치)에 수렴하는지 검증.
    _compute_score는 st.last_* 값을 읽으므로 직접 주입 필요."""
    from src.trading.scalping.constants import W_EXEC_STRENGTH, W_VOL_RATIO, W_OB_IMBALANCE
    eng = SignalEngine()
    eng.register("005930")
    st = eng._states["005930"]
    # 기준값 직접 주입
    st.last_exec_strength = 150.0   # 기준값 → W_EXEC_STRENGTH 만점
    st.last_ob_imbalance = 1.5      # 기준값 → W_OB_IMBALANCE 만점
    st.last_vol_ratio = 3.0         # 기준값 → W_VOL_RATIO 만점
    st.vwap.update_acml(72_000 * 1000, 1000)

    tick = _tick(price=72_000)
    score = eng._compute_score(st, tick, market_strength=1.0)

    assert score.exec_strength_score == pytest.approx(W_EXEC_STRENGTH, abs=0.1)
    assert score.vol_ratio_score     == pytest.approx(W_VOL_RATIO, abs=0.1)
    assert score.ob_imbalance_score  == pytest.approx(W_OB_IMBALANCE, abs=0.1)


def test_signal_engine_score_formula_proportional():
    """체결강도 75 (기준값 150의 50%) → W_EXEC_STRENGTH * 0.5 점."""
    from src.trading.scalping.constants import W_EXEC_STRENGTH
    eng = SignalEngine()
    eng.register("005930")
    st = eng._states["005930"]
    st.last_exec_strength = 75.0   # 150의 50%
    tick = _tick(price=72_000)
    score = eng._compute_score(st, tick, market_strength=0.0)
    assert score.exec_strength_score == pytest.approx(W_EXEC_STRENGTH * 0.5, abs=0.1)


def test_signal_engine_leader_shallow_pullback_enters_now():
    """거래대금 대장주는 -0.3~-1.0% 얕은 눌림에서도 진입 후보가 된다."""
    eng = SignalEngine()
    eng.register("005930")
    eng.inject_atr_candles("005930", _make_candles(14, high=10_100, low=9_900, close=10_000))
    eng.update_scan_context(
        "005930",
        price=10_000,
        vol_ratio=3.5,
        leader_rank=1,
        leader_score=82.0,
    )

    tick = _tick(
        symbol="005930",
        price=9_950,                 # 기준 고점 대비 -0.5%
        buy_vol=6_000,
        sell_vol=4_000,              # 체결강도 120
        bid=3_000,
        ask=1_500,
        acml_vol=1_000,
        acml_pbmn=9_900 * 1_000,     # VWAP 위 +0.5%
    )
    result = eng.process_tick(tick, market_strength=1.0)

    assert result is not None
    assert result.action == "enter_now"
    assert "leader_shallow_pullback" in result.reason


def test_signal_engine_follower_does_not_use_shallow_pullback_path():
    """후순위 종목은 기존 deep pullback/breakout 경로를 유지한다."""
    eng = SignalEngine()
    eng.register("005930")
    eng.inject_atr_candles("005930", _make_candles(14, high=10_100, low=9_900, close=10_000))
    eng.update_scan_context(
        "005930",
        price=10_000,
        vol_ratio=3.5,
        leader_rank=4,
        leader_score=82.0,
    )

    tick = _tick(
        symbol="005930",
        price=9_950,
        buy_vol=6_000,
        sell_vol=4_000,
        bid=3_000,
        ask=1_500,
        acml_vol=1_000,
        acml_pbmn=9_900 * 1_000,
    )
    result = eng.process_tick(tick, market_strength=1.0)

    assert result is None or "leader_shallow_pullback" not in result.reason


def test_signal_engine_update_scan_context_refreshes_leader_and_high():
    eng = SignalEngine()
    eng.update_scan_context(
        "005930",
        price=10_000,
        vol_ratio=2.5,
        leader_rank=1,
        leader_score=75.0,
    )
    st = eng.get_symbol_state("005930")

    assert st is not None
    assert st.last_vol_ratio == pytest.approx(2.5)
    assert st.leader_rank == 1
    assert st.leader_score == pytest.approx(75.0)
    assert st.pullback.high == pytest.approx(10_000)

    eng.update_scan_context(
        "005930",
        price=10_020,
        vol_ratio=3.0,
        leader_rank=1,
        leader_score=80.0,
    )

    assert st.last_vol_ratio == pytest.approx(3.0)
    assert st.pullback.high == pytest.approx(10_020)


# ─────────────────────────────────────────────────────────────────────────────
# PositionManager
# ─────────────────────────────────────────────────────────────────────────────

def _fill(symbol="005930", side="buy", price=72_000, qty=10, reason="entry_1") -> FillEvent:
    commission = price * qty * 0.00015
    tax = price * qty * 0.0018 if side == "sell" else 0.0
    return FillEvent(
        order_no="ORD001", symbol=symbol, side=side,
        filled_qty=qty, fill_price=price,
        commission=commission, tax=tax, reason=reason,
    )


def test_position_open_on_fill():
    pm = PositionManager()
    fill = _fill()
    pos = pm.on_fill_entry(fill, atr=500.0)
    assert pos.symbol == "005930"
    assert pos.remaining_qty == 10
    assert pos.hard_stop < 72_000
    assert pos.phase == PositionPhase.ENTERING


def test_position_hard_stop_below_entry():
    pm = PositionManager()
    fill = _fill(price=72_000, qty=10)
    pos = pm.on_fill_entry(fill, atr=500.0)
    # hard_stop = entry - ATR × 1.2 = 72000 - 600 = 71400
    assert pos.hard_stop == pytest.approx(71_400.0, abs=10)


def test_position_trailing_stop_updates():
    pm = PositionManager()
    fill = _fill(price=72_000, qty=10)
    pos = pm.on_fill_entry(fill, atr=500.0)

    tick = TickEvent(
        symbol="005930", price=74_000,
        buy_vol_total=6000, sell_vol_total=4000,
        bid_qty=2000, ask_qty=1000,
        tick_vol=50, acml_vol=0, acml_tr_pbmn=0,
        time_str="101000",
    )
    pm._update_trailing(pos, 74_000)
    assert pos.trailing_high == 74_000
    assert pos.trailing_stop > 72_000   # 최고가 기준 trailing


def test_position_tp1_fires_at_2pct():
    pm = PositionManager()
    fill = _fill(price=72_000, qty=10)
    pm.on_fill_entry(fill, atr=500.0)

    tick = TickEvent(
        symbol="005930", price=73_440,  # +2.0%
        buy_vol_total=6000, sell_vol_total=4000,
        bid_qty=2000, ask_qty=1000,
        tick_vol=50, acml_vol=0, acml_tr_pbmn=0,
        time_str="101000",
    )
    req = pm.check_exits("005930", tick, exec_strength=160, ob_imbalance=2.0,
                         vwap=70_000, now_time=dtime(10, 10))
    assert req is not None
    assert req.reason == "exit_tp1"
    assert req.qty == 3   # 30% of 10


def test_position_break_even_stop_set_after_tp1():
    pm = PositionManager()
    fill = _fill(price=72_000, qty=10)
    pm.on_fill_entry(fill, atr=500.0)

    sell_fill = _fill(side="sell", price=73_440, qty=3, reason="exit_tp1")
    pos = pm.on_fill_exit(sell_fill)
    assert pos.break_even_stop == pytest.approx(72_000.0)
    assert pos.phase == PositionPhase.PARTIAL_1


def test_position_force_close_at_1520():
    pm = PositionManager()
    pm.on_fill_entry(_fill(), atr=500.0)
    tick = TickEvent(
        symbol="005930", price=72_000,
        buy_vol_total=5000, sell_vol_total=5000,
        bid_qty=1000, ask_qty=1000,
        tick_vol=50, acml_vol=0, acml_tr_pbmn=0,
        time_str="152000",
    )
    req = pm.check_exits("005930", tick, exec_strength=100, ob_imbalance=1.0,
                         vwap=71_000, now_time=dtime(15, 20))
    assert req is not None
    assert req.reason == "exit_time_force"


def test_position_hard_stop_triggers():
    pm = PositionManager()
    pm.on_fill_entry(_fill(price=72_000), atr=500.0)
    tick = TickEvent(
        symbol="005930", price=71_000,  # 아래 hard_stop
        buy_vol_total=4000, sell_vol_total=6000,
        bid_qty=1000, ask_qty=2000,
        tick_vol=200, acml_vol=0, acml_tr_pbmn=0,
        time_str="103000",
    )
    req = pm.check_exits("005930", tick, exec_strength=60, ob_imbalance=0.5,
                         vwap=71_500, now_time=dtime(10, 30))
    assert req is not None
    assert req.reason == "exit_sl"


# ─────────────────────────────────────────────────────────────────────────────
# RiskManager
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_approve_entry_ok():
    rm = RiskManager(capital=10_000_000)
    approved, reason = rm.approve_entry("005930", 1_000_000, 0, 0.0, market_strength_ok=True)
    assert approved
    assert reason == "ok"


def test_risk_consecutive_loss_blocks():
    rm = RiskManager(capital=10_000_000)
    # 3회 손절 (각각 다른 종목), 연속 손절 카운터 3에 도달
    symbols = ["005930", "000660", "035720"]
    for sym in symbols:
        rm.record_trade(sym, -50_000, 750, is_partial=False)   # -0.5% each → 총 -1.5%
    # 새로운 종목 진입 시 연속 손절 차단 확인
    approved, reason = rm.approve_entry("035420", 1_000_000, 0, 0.0)
    assert not approved
    assert "연속 손절" in reason


def test_risk_win_reduces_consecutive_counter():
    rm = RiskManager(capital=10_000_000)
    rm.record_trade("005930", -100_000, 1_500)
    rm.record_trade("005930", -100_000, 1_500)
    assert rm.state.consecutive_losses == 2
    rm.record_trade("005930", +200_000, 1_500)
    assert rm.state.consecutive_losses == 1


def test_risk_daily_loss_limit_halts():
    rm = RiskManager(capital=10_000_000)
    rm.record_trade("005930", -300_001, 0)   # -3.0001% → 한도 초과
    assert rm.is_halted


def test_risk_unrealized_triggers_halt():
    rm = RiskManager(capital=10_000_000)
    rm.update_unrealized(-310_000)
    assert rm.is_halted


def test_risk_kosdaq_halt():
    rm = RiskManager(capital=10_000_000)
    rm.update_kosdaq(-0.016)
    assert rm.is_halted
    assert "KOSDAQ" in rm.state.halt_reason


def test_risk_blocked_symbol():
    rm = RiskManager(capital=10_000_000)
    # block_symbol 대신 VI 쿨다운으로 진입 차단 검증
    rm.set_vi_cooldown("005930")
    approved, reason = rm.approve_entry("005930", 1_000_000, 0, 0.0)
    assert not approved
    assert "쿨다운" in reason


def test_risk_max_symbols():
    rm = RiskManager(capital=10_000_000)
    approved, reason = rm.approve_entry("000660", 1_000_000, current_positions_count=3, total_exposure=0.0)
    assert not approved
    assert "종목 수" in reason


def test_risk_to_dict_structure():
    rm = RiskManager(capital=10_000_000)
    d = rm.to_dict()
    assert "realized_pnl" in d
    assert "win_rate" in d
    assert "is_halted" in d
    assert "adaptive_min_score" in d


def test_risk_max_daily_trades():
    """일일 최대 거래 횟수(10회) 초과 시 진입 차단."""
    from src.trading.scalping.constants import MAX_DAILY_TRADES
    rm = RiskManager(capital=10_000_000)
    for i in range(MAX_DAILY_TRADES):
        rm.record_entry(f"SYM{i:03d}")
    approved, reason = rm.approve_entry("NEW001", 500_000, 0, 0.0)
    assert not approved
    assert "일일 최대" in reason


def test_risk_max_trades_per_symbol():
    """종목별 최대 거래 횟수(2회) 초과 시 진입 차단."""
    from src.trading.scalping.constants import MAX_TRADES_PER_SYMBOL
    rm = RiskManager(capital=10_000_000)
    for _ in range(MAX_TRADES_PER_SYMBOL):
        rm.record_entry("005930")
    approved, reason = rm.approve_entry("005930", 500_000, 0, 0.0)
    assert not approved
    assert "종목별" in reason


def test_risk_max_trades_per_strategy():
    from src.trading.scalping.constants import MAX_TRADES_PER_STRATEGY
    rm = RiskManager(capital=10_000_000)
    for i in range(MAX_TRADES_PER_STRATEGY):
        rm.record_entry(f"SYM{i:03d}", strategy_name="leader_only_shallow_pullback")

    approved, reason = rm.approve_entry(
        "NEW001",
        500_000,
        0,
        0.0,
        strategy_name="leader_only_shallow_pullback",
    )

    assert not approved
    assert "전략별 최대" in reason


def test_risk_symbol_loss_limit_blocks_reentry():
    rm = RiskManager(capital=10_000_000)
    rm.record_trade("005930", -101_000, 0)

    approved, reason = rm.approve_entry("005930", 500_000, 0, 0.0)

    assert not approved
    assert "종목당 손실 한도" in reason


def test_risk_adaptive_min_score_rises_with_losses():
    """연속 손절에 따라 adaptive_min_score가 올라가는지 확인."""
    from src.trading.scalping.constants import MIN_ENTRY_SCORE, ADAPTIVE_SCORE_LOSS_1, ADAPTIVE_SCORE_LOSS_2
    rm = RiskManager(capital=10_000_000)
    assert rm.adaptive_min_score() == pytest.approx(MIN_ENTRY_SCORE)
    rm.record_trade("005930", -10_000, 0)
    assert rm.adaptive_min_score() == pytest.approx(MIN_ENTRY_SCORE + ADAPTIVE_SCORE_LOSS_1)
    rm.record_trade("000660", -10_000, 0)
    assert rm.adaptive_min_score() == pytest.approx(MIN_ENTRY_SCORE + ADAPTIVE_SCORE_LOSS_2)


def test_position_trailing_stop_never_rolls_back():
    """trailing_stop은 한 번 올라가면 내려가지 않아야 한다."""
    pm = PositionManager()
    fill = _fill(price=72_000, qty=10)
    pos = pm.on_fill_entry(fill, atr=500.0)

    pm._update_trailing(pos, 75_000)   # 최고가 75000 → stop 상승
    stop_at_75k = pos.trailing_stop

    # 가격이 급등 후 일부 되돌림을 계산기에 반영해도 stop 감소 없어야 함
    pm._update_trailing(pos, 74_000)   # 74000은 75000보다 낮음 → high 갱신 안 됨
    assert pos.trailing_stop == stop_at_75k   # 변하지 않아야 함
