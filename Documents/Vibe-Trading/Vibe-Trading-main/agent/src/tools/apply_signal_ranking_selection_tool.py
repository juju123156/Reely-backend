"""Tool: bridge ranking artifacts into selected_symbols for orchestrator configs."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.orchestrator_runner import apply_signal_ranking_selection


class ApplySignalRankingSelectionTool(BaseTool):
    """Read a ranking artifact and persist selected_symbols into config.json."""

    name = "apply_signal_ranking_selection"
    description = (
        "Read JSON/CSV ranking artifacts produced by signal generation or research steps, "
        "extract symbol_scores, and write selected_symbols back to config.json."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Config path relative to run_dir, usually config.json"},
            "ranking_path": {
                "type": "string",
                "description": "Ranking artifact path relative to run_dir, such as artifacts/symbol_scores.json",
            },
            "as_of": {
                "type": "string",
                "description": "Optional timestamp selector when the artifact contains multiple snapshots",
            },
            "max_positions": {
                "type": "integer",
                "description": "Maximum number of symbols to keep after ranking",
            },
            "exclude_symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Symbols to remove before final selection",
            },
            "selection_reason": {
                "type": "string",
                "description": "Short audit note explaining why this ranking was used",
            },
        },
        "required": ["path", "ranking_path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for apply_signal_ranking_selection"}, ensure_ascii=False)

        result = apply_signal_ranking_selection(
            kwargs["path"],
            run_dir=run_dir,
            ranking_path=kwargs["ranking_path"],
            as_of=kwargs.get("as_of"),
            max_positions=kwargs.get("max_positions"),
            exclude_symbols=kwargs.get("exclude_symbols"),
            selection_reason=kwargs.get("selection_reason"),
        )
        return json.dumps(result, ensure_ascii=False)
