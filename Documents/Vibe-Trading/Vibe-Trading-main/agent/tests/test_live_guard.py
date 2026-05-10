from __future__ import annotations

from src.trading.scalping.live_guard import LiveGuardConfig, LiveKillSwitchGuard


def test_live_guard_trips_on_repeated_stale_tick():
    guard = LiveKillSwitchGuard(LiveGuardConfig(stale_tick_sec=5, stale_tick_repeats=2))

    assert guard.observe_tick_age(5.1) == ""
    assert guard.observe_tick_age(5.2) == "tick_stale_repeated"


def test_live_guard_resets_stale_counter_on_fresh_tick():
    guard = LiveKillSwitchGuard(LiveGuardConfig(stale_tick_sec=5, stale_tick_repeats=2))

    assert guard.observe_tick_age(5.1) == ""
    assert guard.observe_tick_age(1.0) == ""
    assert guard.observe_tick_age(5.2) == ""


def test_live_guard_trips_on_order_timeouts_and_slippage():
    guard = LiveKillSwitchGuard(LiveGuardConfig(order_timeout_limit=2, slippage_limit_pct=0.003, slippage_repeats=2))

    assert guard.observe_order_timeout() == ""
    assert guard.observe_order_timeout() == "order_timeout_repeated"

    guard = LiveKillSwitchGuard(LiveGuardConfig(order_timeout_limit=2, slippage_limit_pct=0.003, slippage_repeats=2))
    assert guard.observe_slippage(0.004) == ""
    assert guard.observe_slippage(0.004) == "slippage_exceeded_repeated"
