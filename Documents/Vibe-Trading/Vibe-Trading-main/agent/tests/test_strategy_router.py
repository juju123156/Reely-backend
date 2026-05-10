from __future__ import annotations

import json
from datetime import time as dtime
from pathlib import Path

from src.trading.scalping.events import TickEvent
from src.trading.scalping.market_scanner import SymbolCandidate
from src.trading.scalping.position_type import PositionType
from src.trading.scalping.risk_manager import RiskManager
from src.trading.scalping.strategy_journal import StrategySignalJournal
from src.trading.scalping.strategy_router import IntradayStrategyRouter, StrategyConflictResolver
from src.trading.scalping.strategy_types import StrategyContext, StrategyMode, StrategyName, StrategySignal


def _candidate(**kwargs) -> SymbolCandidate:
    defaults = dict(
        symbol="005930",
        name="삼성전자",
        price=10_000,
        change_pct=0.06,
        trading_value=30_000_000_000,
        volume=300_000,
        exec_strength=125.0,
        prev_same_time_vol=100_000,
        leader_rank=1,
        leader_score=82.0,
    )
    defaults.update(kwargs)
    return SymbolCandidate(**defaults)


def _tick(price=10_000) -> TickEvent:
    return TickEvent(
        symbol="005930",
        price=price,
        buy_vol_total=6_000,
        sell_vol_total=4_000,
        bid_qty=2_000,
        ask_qty=1_000,
        tick_vol=100,
        acml_vol=1_000,
        acml_tr_pbmn=price * 1_000,
        time_str="100000",
        bid1_price=price - 5,
        ask1_price=price + 5,
    )


def _context(now_time, candidate=None, **snapshot) -> StrategyContext:
    snap = {
        "exec_strength": 120.0,
        "ob_imbalance": 1.2,
        "vwap_gap": 0.004,
        "vol_ratio": 3.0,
        "pullback_pct": 0.006,
    }
    snap.update(snapshot)
    return StrategyContext(
        now_time=now_time,
        regime="kosdaq_normal",
        market_ok=True,
        candidate=candidate or _candidate(),
        signal_snapshot=snap,
    )


def test_router_selects_opening_momentum_0905_0920():
    router = IntradayStrategyRouter()
    active = router.select_active_strategies(dtime(9, 10), "kosdaq_normal", {})
    modes = {a.name: a.mode for a in active}

    assert modes[StrategyName.OPENING_MOMENTUM] == StrategyMode.SHADOW
    assert modes[StrategyName.SHALLOW_PULLBACK] == StrategyMode.SHADOW


def test_router_selects_shallow_pullback_0920_1030():
    router = IntradayStrategyRouter()
    active = router.select_active_strategies(dtime(9, 30), "kosdaq_normal", {})
    modes = {a.name: a.mode for a in active}

    assert modes[StrategyName.SHALLOW_PULLBACK] == StrategyMode.LIVE
    assert modes[StrategyName.LEADER_ROTATION] == StrategyMode.LIVE


def test_router_selects_vwap_reclaim_1030_1300():
    router = IntradayStrategyRouter()
    active = router.select_active_strategies(dtime(11, 0), "kosdaq_normal", {})
    modes = {a.name: a.mode for a in active}

    assert modes[StrategyName.VWAP_RECLAIM] == StrategyMode.SHADOW


def test_router_disables_intraday_after_1450():
    router = IntradayStrategyRouter()
    active = router.select_active_strategies(dtime(14, 55), "kosdaq_normal", {})

    assert [a.name for a in active] == [StrategyName.CLOSE_BET]


def test_strategy_mode_shadow_no_live_order():
    router = IntradayStrategyRouter()
    signals = router.route_tick(_tick(), None, _context(dtime(9, 10)))

    assert signals
    assert all(s.shadow_only for s in signals)
    assert all(not s.live_allowed for s in signals)


def test_strategy_mode_live_sends_order():
    router = IntradayStrategyRouter()
    signals = router.route_tick(_tick(price=9_950), None, _context(dtime(9, 30), pullback_pct=0.006))
    live = [s for s in signals if s.live_allowed and not s.shadow_only]

    assert live
    assert live[0].strategy_name == "shallow_pullback"


def test_shallow_pullback_leader_threshold_relaxed():
    router = IntradayStrategyRouter()
    signals = router.route_tick(_tick(price=9_950), None, _context(dtime(9, 30), pullback_pct=0.004))

    assert any(s.strategy_name == "shallow_pullback" and s.live_allowed for s in signals)


def test_follower_uses_deep_pullback_threshold():
    router = IntradayStrategyRouter()
    follower = _candidate(leader_rank=4, leader_score=55.0)
    routed = router.route_candidates([follower], _context(dtime(9, 30), candidate=follower))

    assert not any(c.strategy_name == "shallow_pullback" for c in routed)
    assert any(c.strategy_name == "vwap_reclaim" for c in routed) is False


def test_opening_momentum_shadow_signal():
    router = IntradayStrategyRouter()
    signals = router.route_tick(_tick(), None, _context(dtime(9, 10)))

    assert any(s.strategy_name == "opening_momentum" and s.shadow_only for s in signals)


def test_vwap_reclaim_shadow_signal():
    router = IntradayStrategyRouter()
    signals = router.route_tick(_tick(), None, _context(dtime(11, 0), vwap_gap=0.003, vol_ratio=2.0))

    assert any(s.strategy_name == "vwap_reclaim" and s.shadow_only for s in signals)


def test_leader_rotation_blocks_etf():
    router = IntradayStrategyRouter()
    etf = _candidate(is_etf=True)
    routed = router.route_candidates([etf], _context(dtime(9, 30), candidate=etf))

    assert not any(c.strategy_name == "shallow_pullback" for c in routed)
    assert not any(c.strategy_name == "opening_momentum" for c in routed)


def test_conflict_resolver_exit_over_buy():
    resolver = StrategyConflictResolver()
    buy = StrategySignal("shallow_pullback", "005930", "buy", 0.8, 0.01, 10_000, 9_900, 10_100, PositionType.INTRADAY_SCALP, True, False, "buy", {})
    sell = StrategySignal("exit", "005930", "sell", 1.0, 0.0, 10_000, None, None, PositionType.INTRADAY_SCALP, True, False, "exit", {})

    assert resolver.resolve([buy, sell]) == [sell]


def test_conflict_resolver_one_live_buy_per_symbol():
    resolver = StrategyConflictResolver()
    a = StrategySignal("shallow_pullback", "005930", "buy", 0.8, 0.01, 10_000, 9_900, 10_100, PositionType.INTRADAY_SCALP, True, False, "a", {})
    b = StrategySignal("vwap_reclaim", "005930", "buy", 0.9, 0.02, 10_000, 9_900, 10_100, PositionType.INTRADAY_SCALP, True, False, "b", {})

    resolved = resolver.resolve([a, b])

    assert len([s for s in resolved if s.live_allowed and not s.shadow_only]) == 1


def test_strategy_exposure_limit():
    rm = RiskManager(capital=10_000_000)

    approved, _ = rm.approve_strategy_exposure("opening_momentum", amount=200_000)
    rejected, reason = rm.approve_strategy_exposure("opening_momentum", amount=400_000)

    assert approved
    assert not rejected
    assert "전략 비중 초과" in reason


def test_strategy_jsonl_written(tmp_path: Path):
    journal = StrategySignalJournal(shadow_dir=tmp_path / "shadow", live_dir=tmp_path / "live")
    signal = StrategySignal("vwap_reclaim", "005930", "buy", 0.7, 0.01, 10_000, 9_900, 10_100, PositionType.INTRADAY_SCALP, False, True, "shadow", {})

    journal.record_signal(signal, mode="shadow")

    rows = list((tmp_path / "shadow").glob("*.jsonl"))
    assert rows
    payload = json.loads(rows[0].read_text(encoding="utf-8").splitlines()[0])
    assert payload["strategy"] == "vwap_reclaim"
    assert payload["mode"] == "shadow"


def test_dashboard_strategy_summary():
    router = IntradayStrategyRouter()
    router.route_tick(_tick(), None, _context(dtime(11, 0), vwap_gap=0.003, vol_ratio=2.0))
    summary = router.last_summary

    assert "active_strategies" in summary
    assert "shadow_strategies" in summary
    assert "live_strategies" in summary
    assert summary["signal_count"] >= 1
