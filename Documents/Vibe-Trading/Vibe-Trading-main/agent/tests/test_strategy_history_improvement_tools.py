from __future__ import annotations

import json
from pathlib import Path

from src.tools.strategy_history_improvement_tools import (
    AnalyzeStrategyHistoryTool,
    EvaluateImprovementCandidatesTool,
    GenerateImprovementCandidatesTool,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_analyze_and_generate_candidates_tools(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    history_path = run_dir / "history.json"
    _write_json(history_path, {
        "trades": [
            {"symbol": "005930.KS", "pnl": -100, "exit_reason": "time_stop", "session_bucket": "opening"},
            {"symbol": "005930.KS", "pnl": -50, "exit_reason": "time_stop", "session_bucket": "opening"},
            {"symbol": "000660.KS", "pnl": 20, "exit_reason": "signal_exit", "session_bucket": "morning"}
        ]
    })

    analyze = json.loads(AnalyzeStrategyHistoryTool().execute(history_path="history.json", run_dir=str(run_dir)))
    assert analyze["status"] == "ok"

    generate = json.loads(
        GenerateImprovementCandidatesTool().execute(
            diagnostic_path="artifacts/diagnostic_report.json",
            run_dir=str(run_dir),
        )
    )
    assert generate["status"] == "ok"
    assert generate["improvement_candidates"]["candidates"]


def test_evaluate_improvement_candidates_tool(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    comparison_path = run_dir / "comparison.json"
    _write_json(comparison_path, {
        "strategy_id": "kr-open",
        "strategy_version": "v1",
        "baseline": {"total_return": 0.1, "max_drawdown": -0.08},
        "candidates": [
            {"candidate_id": "tighten-time-stop", "title": "Tighten time stop", "metrics": {"total_return": 0.13, "max_drawdown": -0.08, "trade_count": 25}}
        ]
    })

    result = json.loads(
        EvaluateImprovementCandidatesTool().execute(
            comparison_path="comparison.json",
            run_dir=str(run_dir),
            min_return_delta=0.01,
        )
    )

    assert result["status"] == "ok"
    assert result["promotion_decision"]["status"] == "APPROVED"
