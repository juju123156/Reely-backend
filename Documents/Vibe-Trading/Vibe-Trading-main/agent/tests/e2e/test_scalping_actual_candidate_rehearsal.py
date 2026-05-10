from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.trading.scalping.strategy_promotion import PromotionState

from tests.fixtures.e2e_scenarios import ScenarioConfig, ScalpingE2EHarness
from tests.fixtures.fake_orderbook import FakeOrderbook
from tests.fixtures.fake_ticks import make_tick


ETF_PREFIXES = ("TIGER", "KODEX", "KBSTAR", "ACE", "SOL", "HANARO", "ARIRANG", "KOSEF")


def _latest_live_candidate() -> dict:
    base = Path(__file__).resolve().parents[2] / "data" / "shadow_trading"
    rows: list[dict] = []
    for path in sorted(base.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_type") != "candidate_scan":
                continue
            name = str(row.get("name") or "")
            if any(prefix in name for prefix in ETF_PREFIXES):
                continue
            if int(row.get("leader_rank") or 999) <= 2 and float(row.get("leader_score") or 0.0) >= 60.0:
                rows.append(row)
    if not rows:
        pytest.skip("No actual leader candidate with rank<=2 and leader_score>=60 in shadow_trading data")
    return rows[-1]


def _book(price: float, *, age_sec: float = 0.2) -> FakeOrderbook:
    return FakeOrderbook(
        bid1=price,
        ask1=price + 10,
        bid_qty=50_000,
        ask_qty=10_000,
        age_sec=age_sec,
        depth_levels=5,
    )


def test_actual_filtered_candidate_buy_take_profit_rehearsal(tmp_path):
    candidate = _latest_live_candidate()
    price = float(candidate["scan_price"])
    symbol = str(candidate["symbol"])
    cfg = ScenarioConfig(
        symbol=symbol,
        strategy="leader_only_shallow_pullback",
        promotion_state=PromotionState.SMALL_LIVE,
        qty=10,
        atr=max(10.0, price * 0.003),
        leader_score=float(candidate.get("leader_score") or 0.0),
    )
    harness = ScalpingE2EHarness(tmp_path, cfg)

    entry_tick = make_tick(symbol=symbol, price=price, book=_book(price), ts=harness.clock.now)
    buy_fill = asyncio.run(harness.enter(entry_tick))

    assert buy_fill is not None
    assert harness.journal.count("live_order_attempt") == 1
    assert harness.journal.latest("broker_reconcile_event")["ok"] is True

    exit_price = price * 1.012
    exit_tick = make_tick(symbol=symbol, price=exit_price, book=_book(exit_price), ts=harness.clock.advance(30))
    sell_fill = asyncio.run(harness.exit_if_triggered(exit_tick))
    report = harness.write_daily_report()

    assert sell_fill is not None
    assert harness.journal.latest("exit_signal")["reason"] == "exit_tp1"
    assert harness.journal.latest("pnl_event")["pnl"] > 0
    assert report["pnl"] > 0
    assert harness.journal.latest("daily_strategy_report")["pnl"] > 0


def test_actual_filtered_candidate_buy_stop_loss_rehearsal(tmp_path):
    candidate = _latest_live_candidate()
    price = float(candidate["scan_price"])
    symbol = str(candidate["symbol"])
    cfg = ScenarioConfig(
        symbol=symbol,
        strategy="leader_only_shallow_pullback",
        promotion_state=PromotionState.SMALL_LIVE,
        qty=10,
        atr=10.0,
        leader_score=float(candidate.get("leader_score") or 0.0),
    )
    harness = ScalpingE2EHarness(tmp_path, cfg)

    entry_tick = make_tick(symbol=symbol, price=price, book=_book(price), ts=harness.clock.now)
    assert asyncio.run(harness.enter(entry_tick)) is not None

    stop_price = price * 0.989
    stop_tick = make_tick(symbol=symbol, price=stop_price, book=_book(stop_price), ts=harness.clock.advance(30))
    sell_fill = asyncio.run(harness.exit_if_triggered(stop_tick))

    assert sell_fill is not None
    assert harness.journal.latest("exit_signal")["reason"] == "exit_sl"
    assert harness.journal.latest("pnl_event")["pnl"] < 0
    assert harness.risk.state.loss_count == 1
