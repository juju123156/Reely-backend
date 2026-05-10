from __future__ import annotations

import json
from pathlib import Path

from src.trading.history_improver import (
    build_diagnostic_report,
    build_improvement_candidates,
    build_promotion_decision,
    write_history_improvement_artifacts,
)


def _sample_history() -> list[dict]:
    return [
        {"symbol": "005930.KS", "entry_time": "2026-04-01T09:05:00", "exit_time": "2026-04-01T10:30:00", "pnl": -1000, "hold_minutes": 85, "exit_reason": "time_stop", "session_bucket": "opening"},
        {"symbol": "005930.KS", "entry_time": "2026-04-02T09:10:00", "exit_time": "2026-04-02T10:30:00", "pnl": -500, "hold_minutes": 80, "exit_reason": "time_stop", "session_bucket": "opening"},
        {"symbol": "000660.KS", "entry_time": "2026-04-03T10:05:00", "exit_time": "2026-04-03T10:45:00", "pnl": 300, "hold_minutes": 40, "exit_reason": "signal_exit", "session_bucket": "morning"},
        {"symbol": "005930.KS", "entry_time": "2026-04-04T09:05:00", "exit_time": "2026-04-04T10:30:00", "pnl": -200, "hold_minutes": 85, "exit_reason": "time_stop", "session_bucket": "opening"},
    ]


def _sample_history_with_ranked_candidates() -> list[dict]:
    return [
        {
            "symbol": "005930.KS",
            "pnl": -100,
            "entry_signal_snapshot": {
                "ranked_candidates": [
                    {"symbol": "005930.KS", "selected": True, "rank": 1, "score": 0.91, "realized_pnl": -100},
                    {"symbol": "000660.KS", "selected": False, "rank": 2, "score": 0.88, "realized_pnl": 250},
                ]
            },
        },
        {
            "symbol": "035420.KS",
            "pnl": 50,
            "entry_signal_snapshot": {
                "ranked_candidates": [
                    {"symbol": "035420.KS", "selected": True, "rank": 1, "score": 0.77, "realized_pnl": 50},
                    {"symbol": "000660.KS", "selected": False, "rank": 2, "score": 0.70, "realized_pnl": 120},
                ]
            },
        },
    ]


def test_build_diagnostic_report_detects_issues() -> None:
    report = build_diagnostic_report(_sample_history(), strategy_id="kr-open", strategy_version="v1")

    assert report["strategy_id"] == "kr-open"
    issues = {issue["issue"] for issue in report["issues"]}
    assert "over_reliance_on_time_stop" in issues
    assert "symbol_concentration" in issues


def test_build_improvement_candidates_returns_small_changes() -> None:
    report = build_diagnostic_report(_sample_history())
    candidates = build_improvement_candidates(report, max_candidates=5)

    ids = {candidate["candidate_id"] for candidate in candidates["candidates"]}
    assert "tighten-time-stop" in ids
    assert "reduce-top-n" in ids


def test_build_diagnostic_report_detects_selection_miss_rate() -> None:
    report = build_diagnostic_report(_sample_history_with_ranked_candidates())

    selection_issue = next(issue for issue in report["issues"] if issue["issue"] == "selection_miss_rate")
    assert selection_issue["evaluated_entries"] == 2
    assert selection_issue["miss_rate"] == 1.0
    assert selection_issue["miss_examples"][0]["better_rejected_symbol"] == "000660.KS"


def test_build_improvement_candidates_adds_selection_candidates() -> None:
    report = build_diagnostic_report(_sample_history_with_ranked_candidates())
    candidates = build_improvement_candidates(report, max_candidates=10)

    ids = {candidate["candidate_id"] for candidate in candidates["candidates"]}
    assert "tighten-selection-threshold" in ids
    assert "reweight-ranking-inputs" in ids


def test_build_promotion_decision_approves_best_candidate() -> None:
    comparison, promotion = build_promotion_decision(
        {
            "strategy_id": "kr-open",
            "strategy_version": "v1",
            "baseline": {"total_return": 0.12, "max_drawdown": -0.08},
            "candidates": [
                {"candidate_id": "a", "title": "A", "metrics": {"total_return": 0.15, "max_drawdown": -0.08, "trade_count": 35}},
                {"candidate_id": "b", "title": "B", "metrics": {"total_return": 0.10, "max_drawdown": -0.05, "trade_count": 40}},
            ],
        },
        min_return_delta=0.01,
        max_drawdown_regression=0.01,
        min_trade_count=20,
    )

    assert comparison["candidates"][0]["candidate_id"] == "a"
    assert promotion["status"] == "APPROVED"
    assert promotion["selected_candidate_id"] == "a"


def test_write_history_improvement_artifacts_writes_files(tmp_path: Path) -> None:
    outputs = write_history_improvement_artifacts(
        tmp_path,
        diagnostic_report={"x": 1},
        improvement_candidates={"y": 2},
        promotion_decision={"z": 3},
    )

    assert "diagnostic_report" in outputs
    assert json.loads(outputs["promotion_decision"].read_text(encoding="utf-8"))["z"] == 3
