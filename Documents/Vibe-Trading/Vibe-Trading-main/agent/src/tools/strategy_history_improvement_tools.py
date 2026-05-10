"""Tools for strategy improvement from execution history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_path
from src.trading.history_improver import (
    _extract_history_rows,
    _load_json_payload,
    _resolve_input_path,
    build_diagnostic_report,
    build_improvement_candidates,
    build_promotion_decision,
    write_history_improvement_artifacts,
)


class AnalyzeStrategyHistoryTool(BaseTool):
    name = "analyze_strategy_history"
    description = "Analyze strategy trade history or execution logs and write artifacts/diagnostic_report.json."
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "history_path": {"type": "string", "description": "JSON history path. Relative to run_dir or absolute under user home/project."},
            "strategy_id": {"type": "string"},
            "strategy_version": {"type": "string"},
        },
        "required": ["history_path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for analyze_strategy_history"}, ensure_ascii=False)
        history_path = _resolve_input_path(kwargs["history_path"], run_dir=run_dir)
        payload = _load_json_payload(history_path)
        rows = _extract_history_rows(payload)
        report = build_diagnostic_report(
            rows,
            strategy_id=str(kwargs.get("strategy_id") or ""),
            strategy_version=str(kwargs.get("strategy_version") or ""),
        )
        outputs = write_history_improvement_artifacts(Path(run_dir), diagnostic_report=report)
        return json.dumps({
            "status": "ok",
            "history_path": str(history_path),
            "records": len(rows),
            "artifacts": {name: str(path) for name, path in outputs.items()},
            "diagnostic_report": report,
        }, ensure_ascii=False)


class GenerateImprovementCandidatesTool(BaseTool):
    name = "generate_improvement_candidates"
    description = "Generate small strategy-change hypotheses from artifacts/diagnostic_report.json."
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "diagnostic_path": {"type": "string", "description": "Diagnostic report path relative to run_dir or absolute."},
            "max_candidates": {"type": "integer"},
        },
        "required": ["diagnostic_path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for generate_improvement_candidates"}, ensure_ascii=False)
        diagnostic_path = _resolve_input_path(kwargs["diagnostic_path"], run_dir=run_dir)
        payload = _load_json_payload(diagnostic_path)
        candidates = build_improvement_candidates(payload, max_candidates=_to_int(kwargs.get("max_candidates"), 5))
        outputs = write_history_improvement_artifacts(Path(run_dir), improvement_candidates=candidates)
        return json.dumps({
            "status": "ok",
            "diagnostic_path": str(diagnostic_path),
            "artifacts": {name: str(path) for name, path in outputs.items()},
            "improvement_candidates": candidates,
        }, ensure_ascii=False)


class EvaluateImprovementCandidatesTool(BaseTool):
    name = "evaluate_improvement_candidates"
    description = "Evaluate candidate-vs-baseline comparison JSON and write promotion artifacts."
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "comparison_path": {"type": "string", "description": "Comparison JSON path relative to run_dir or absolute."},
            "min_return_delta": {"type": "number"},
            "max_drawdown_regression": {"type": "number"},
            "min_trade_count": {"type": "integer"},
        },
        "required": ["comparison_path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for evaluate_improvement_candidates"}, ensure_ascii=False)
        comparison_path = _resolve_input_path(kwargs["comparison_path"], run_dir=run_dir)
        payload = _load_json_payload(comparison_path)
        comparison, promotion = build_promotion_decision(
            payload,
            min_return_delta=float(kwargs.get("min_return_delta", 0.0)),
            max_drawdown_regression=float(kwargs.get("max_drawdown_regression", 0.0)),
            min_trade_count=_to_int(kwargs.get("min_trade_count"), 20),
        )
        outputs = write_history_improvement_artifacts(
            Path(run_dir),
            improvement_comparison=comparison,
            promotion_decision=promotion,
        )
        return json.dumps({
            "status": "ok",
            "comparison_path": str(comparison_path),
            "artifacts": {name: str(path) for name, path in outputs.items()},
            "improvement_comparison": comparison,
            "promotion_decision": promotion,
        }, ensure_ascii=False)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
