from __future__ import annotations

import asyncio

from src.trading.scalping.strategy_promotion import PromotionState
from src.trading.scalping.regime_runtime import RuntimeRegime

from tests.fixtures.e2e_scenarios import ScenarioConfig, ScalpingE2EHarness
from tests.fixtures.fake_orderbook import FakeOrderbook
from tests.fixtures.fake_ticks import make_tick


def test_normal_buy_then_take_profit_exit(tmp_path):
    harness = ScalpingE2EHarness(tmp_path)
    entry = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    fill = asyncio.run(harness.enter(entry))
    assert fill is not None

    exit_tick = make_tick(price=10_120, book=FakeOrderbook(10_120, 10_130, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.advance(30))
    exit_fill = asyncio.run(harness.exit_if_triggered(exit_tick))
    report = harness.write_daily_report()

    assert exit_fill is not None
    assert harness.journal.count("signal_generated") == 1
    assert harness.journal.count("live_order_attempt") == 1
    assert harness.journal.latest("exit_signal")["reason"] == "exit_tp1"
    assert harness.journal.latest("pnl_event")["pnl"] > 0
    assert report["pnl"] > 0
    assert {e["record_id"] for e in harness.journal.events if "record_id" in e} == {harness.record_id}


def test_normal_buy_then_stop_loss_exit(tmp_path):
    harness = ScalpingE2EHarness(tmp_path, ScenarioConfig(atr=10))
    entry = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_000, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    assert asyncio.run(harness.enter(entry)) is not None
    stop_tick = make_tick(price=9_900, book=FakeOrderbook(9_900, 9_910, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.advance(30))
    exit_fill = asyncio.run(harness.exit_if_triggered(stop_tick))

    assert exit_fill is not None
    assert harness.journal.latest("exit_signal")["reason"] == "exit_sl"
    assert harness.journal.latest("pnl_event")["pnl"] < 0
    assert harness.risk.state.loss_count == 1
    assert harness.risk.state.consecutive_losses == 1


def test_time_stop_exit_after_no_mfe(tmp_path):
    harness = ScalpingE2EHarness(tmp_path)
    entry = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_000, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    assert asyncio.run(harness.enter(entry)) is not None
    harness.age_position(301)
    flat_tick = make_tick(price=10_005, book=FakeOrderbook(10_005, 10_015, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.advance(301))
    exit_fill = asyncio.run(harness.exit_if_triggered(flat_tick))

    assert exit_fill is not None
    assert harness.journal.latest("exit_signal")["reason"] == "exit_time_no_mfe"
    assert harness.journal.latest("position_event")["state"] == "closed"


def test_partial_fill_then_cancel_and_reconcile(tmp_path):
    harness = ScalpingE2EHarness(tmp_path, ScenarioConfig(qty=100))
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=20_000, ask_qty=40), ts=harness.clock.now)

    asyncio.run(harness.partial_then_cancel(tick))

    states = [e["state"] for e in harness.journal.events if e["event_type"] == "order_state_event"]
    assert "partially_filled" in states
    assert "canceled" in states
    assert harness.positions.get_position("TEST001").remaining_qty == 40
    assert harness.journal.latest("broker_reconcile_event")["ok"] is True


def test_order_timeout_cancels_and_expires_signal(tmp_path):
    harness = ScalpingE2EHarness(tmp_path)
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    asyncio.run(harness.timeout_entry(tick))

    assert "timeout" in [e["state"] for e in harness.journal.events if e["event_type"] == "order_state_event"]
    assert harness.journal.count("signal_expired") == 1
    assert harness.positions.active_positions() == {}


def test_stale_quote_or_orderbook_blocks_live_order(tmp_path):
    cfg = ScenarioConfig(orderbook_age_sec=4.0, tick_age_sec=6.0)
    harness = ScalpingE2EHarness(tmp_path, cfg)
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000, age_sec=4.0), ts=harness.clock.now)

    fill = asyncio.run(harness.enter(tick))

    assert fill is None
    assert harness.journal.count("signal_generated") == 1
    assert harness.journal.count("live_order_attempt") == 0
    assert harness.journal.latest("gatekeeper_snapshot")["terminal_blocker"] in {"stale_orderbook", "stale_tick", "stale_quote"}


def test_shadow_only_promotion_blocks_live_order(tmp_path):
    cfg = ScenarioConfig(strategy="momentum_continuation", promotion_state=PromotionState.SHADOW_ONLY, regime=RuntimeRegime.TRENDING)
    harness = ScalpingE2EHarness(tmp_path, cfg)
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    fill = asyncio.run(harness.enter(tick))

    assert fill is None
    assert harness.journal.count("shadow_entry_created") == 1
    assert harness.journal.count("live_order_attempt") == 0
    assert "promotion_gate_shadow_only" in harness.journal.reasons()


def test_runtime_permission_blocks_vwap_in_choppy_regime(tmp_path):
    cfg = ScenarioConfig(strategy="vwap_reclaim", promotion_state=PromotionState.SMALL_LIVE, regime=RuntimeRegime.CHOPPY)
    harness = ScalpingE2EHarness(tmp_path, cfg)
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    fill = asyncio.run(harness.enter(tick))

    assert fill is None
    assert harness.journal.count("live_order_attempt") == 0
    assert harness.journal.latest("runtime_permission")["allowed"] is False
    assert harness.journal.latest("gatekeeper_snapshot")["terminal_blocker"] in {"strategy_blocked_by_regime", "strategy_not_allowed_by_regime"}


def test_daily_loss_limit_blocks_new_order(tmp_path):
    cfg = ScenarioConfig(daily_pnl=-310_000, capital=10_000_000)
    harness = ScalpingE2EHarness(tmp_path, cfg)
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    fill = asyncio.run(harness.enter(tick))

    assert fill is None
    assert harness.journal.count("live_order_attempt") == 0
    assert "일 손실 한도 도달" in harness.journal.latest("strategy_reject")["reject_reason"]


def test_three_consecutive_losses_pause_strategy_by_risk(tmp_path):
    cfg = ScenarioConfig(consecutive_losses=3)
    harness = ScalpingE2EHarness(tmp_path, cfg)
    tick = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_010, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    fill = asyncio.run(harness.enter(tick))

    assert fill is None
    assert harness.journal.count("live_order_attempt") == 0
    assert "연속 손절" in harness.journal.latest("strategy_reject")["reject_reason"]


def test_session_force_close_intraday_position(tmp_path):
    harness = ScalpingE2EHarness(tmp_path)
    entry = make_tick(price=10_000, book=FakeOrderbook(9_990, 10_000, bid_qty=30_000, ask_qty=10_000), ts=harness.clock.now)

    assert asyncio.run(harness.enter(entry)) is not None
    close_tick = make_tick(price=10_020, book=FakeOrderbook(10_020, 10_030, bid_qty=20_000, ask_qty=20_000), ts=harness.clock.advance(60))
    exit_fill = asyncio.run(harness.force_close(close_tick))

    assert exit_fill is not None
    assert harness.journal.latest("exit_signal")["reason"] == "exit_time_force"
    assert harness.positions.active_positions() == {}
