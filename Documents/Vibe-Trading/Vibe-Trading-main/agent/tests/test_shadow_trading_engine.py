from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from src.trading.scalping.events import TickEvent
from src.trading.scalping.market_scanner import SymbolCandidate
from src.trading.scalping.shadow_trading import ShadowTradingEngine


def _candidate(**kwargs) -> SymbolCandidate:
    defaults = dict(
        symbol="005930",
        name="삼성전자",
        price=10_000,
        change_pct=0.05,
        trading_value=20_000_000_000,
        volume=100_000,
        exec_strength=125.0,
        prev_same_time_vol=40_000,
        leader_rank=1,
        leader_score=82.0,
    )
    defaults.update(kwargs)
    return SymbolCandidate(**defaults)


def _tick(symbol="005930", price=10_100, ts=None) -> TickEvent:
    return TickEvent(
        symbol=symbol,
        price=price,
        buy_vol_total=6_000,
        sell_vol_total=4_000,
        bid_qty=2_000,
        ask_qty=1_000,
        tick_vol=100,
        acml_vol=1_000,
        acml_tr_pbmn=price * 1_000,
        time_str="100000",
        ts=ts or datetime.now(),
    )


def _jsonl_rows(base_dir: Path) -> list[dict]:
    paths = list(base_dir.glob("*.jsonl"))
    assert paths
    rows: list[dict] = []
    for path in paths:
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return rows


def test_shadow_engine_records_scan_and_shadow_entries(tmp_path: Path):
    engine = ShadowTradingEngine(base_dir=tmp_path)
    engine.observe_candidates([_candidate()])

    rows = _jsonl_rows(tmp_path)
    event_types = {row["event_type"] for row in rows}

    assert "candidate_scan" in event_types
    assert "shadow_entry" in event_types
    assert any(row.get("strategy") == "shadow_scan_immediate" for row in rows)
    assert any(row.get("strategy") == "shadow_leader_only" for row in rows)
    assert any(row.get("strategy") == "shadow_score_70" for row in rows)


def test_shadow_engine_records_candidate_mfe_mae_window(tmp_path: Path):
    engine = ShadowTradingEngine(base_dir=tmp_path)
    engine.observe_candidates([_candidate()])
    candidate = engine._candidates["005930"]
    candidate.scan_time = datetime.now() - timedelta(seconds=61)

    engine.on_tick(_tick(price=10_250), signal_snapshot={"exec_strength": 120, "vwap_gap": 0.01})

    rows = _jsonl_rows(tmp_path)
    window_rows = [row for row in rows if row["event_type"] == "candidate_window"]

    window_60 = next(row for row in window_rows if row["window_sec"] == 60)
    assert window_60["mfe_pct"] >= 0.02
    assert window_60["missed_opportunity"] is True


def test_shadow_engine_records_30s_and_rejected_candidate_windows(tmp_path: Path):
    engine = ShadowTradingEngine(base_dir=tmp_path)
    c = _candidate()
    engine.observe_rejected_candidate(
        c,
        strategy="shallow_pullback",
        reject_reason="leader_score_below",
        metrics={"expected_entry_price": 10_000, "ask1_price": 10_010, "bid1_price": 9_990},
    )
    tracked = next(v for v in engine._candidate_events.values() if v.event_type == "rejected_candidate")
    tracked.scan_time = datetime.now() - timedelta(seconds=31)

    engine.on_tick(_tick(price=10_120))

    rows = _jsonl_rows(tmp_path)
    assert any(row["event_type"] == "rejected_candidate_window_30s" for row in rows)
    window = next(row for row in rows if row["event_type"] == "rejected_candidate_window_30s")
    assert window["reject_reason"] == "leader_score_below"
    assert "net_expectancy" in window
    assert "ask1_entry_price" in window


def test_shadow_engine_opens_shallow_pullback_from_ticks(tmp_path: Path):
    engine = ShadowTradingEngine(base_dir=tmp_path)
    engine.observe_candidates([_candidate()])

    engine.on_tick(_tick(price=9_950), signal_snapshot={"exec_strength": 120, "vwap_gap": 0.0})

    rows = _jsonl_rows(tmp_path)
    assert any(
        row.get("event_type") == "shadow_entry"
        and row.get("strategy") == "shadow_shallow_pullback"
        for row in rows
    )


def test_shadow_engine_records_virtual_exit(tmp_path: Path):
    engine = ShadowTradingEngine(base_dir=tmp_path)
    engine.observe_candidates([_candidate()])

    engine.on_tick(_tick(price=10_200), signal_snapshot={"exec_strength": 120, "vwap_gap": 0.01})

    rows = _jsonl_rows(tmp_path)
    exits = [row for row in rows if row["event_type"] == "shadow_exit"]

    assert exits
    assert exits[0]["exit_reason"] in {"take_profit_1", "take_profit_2"}
    assert exits[0]["pnl_pct"] >= 0.01
