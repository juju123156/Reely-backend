from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.trading.scalping.reports import build_daily_strategy_report
from src.trading.scalping.strategy_promotion import PromotionState, StrategyPromotionGate


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_daily_report_writes_promotion_state_for_passing_leader_shallow(tmp_path: Path):
    day = date.today().isoformat()
    shadow = tmp_path / "shadow" / f"{day}.jsonl"
    diag = tmp_path / "diag" / f"{day}.jsonl"

    for idx in range(50):
        _append_jsonl(shadow, {
            "event_type": "rejected_candidate_window_5m",
            "strategy": "leader_only_shallow_pullback",
            "symbol": f"00{idx:04d}",
            "mfe_pct": 0.012,
            "mae_pct": -0.004,
            "net_expectancy": 0.004,
        })
    _append_jsonl(diag, {
        "event_type": "strategy_reject",
        "reject_reason": "leader_score_below",
    })
    _append_jsonl(diag, {
        "event_type": "feature_freshness",
        "last_tick_age_sec": 1,
        "vwap_ready": True,
        "atr_ready": True,
    })

    report = build_daily_strategy_report(
        shadow_dir=tmp_path / "shadow",
        diagnostics_dir=tmp_path / "diag",
        output_dir=tmp_path / "reports",
        promotion_dir=tmp_path / "promotion",
    )

    assert report["strategy_stats"]["leader_only_shallow_pullback"]["sample_count"] == 50
    gate = StrategyPromotionGate(tmp_path / "promotion" / "current.json")
    assert gate.state_for("leader_only_shallow_pullback") == PromotionState.SMALL_LIVE
    assert gate.state_for("shallow_pullback") == PromotionState.SMALL_LIVE
    assert gate.live_allowed("leader_only_shallow_pullback") is True


def test_promotion_gate_defaults_to_shadow_only_without_state(tmp_path: Path):
    gate = StrategyPromotionGate(tmp_path / "missing.json")

    assert gate.state_for("vwap_reclaim") == PromotionState.SHADOW_ONLY
    assert gate.live_allowed("vwap_reclaim") is False
