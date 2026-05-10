"""Tool: derive selected_symbols for orchestrator-managed KR strategy configs."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.orchestrator_runner import select_orchestrator_symbols


class SelectOrchestratorSymbolsTool(BaseTool):
    """Pick final symbols from the configured universe and persist them to config.json."""

    name = "select_orchestrator_symbols"
    description = (
        "Select final symbols for an orchestrator-managed strategy by filtering the config universe, "
        "ranking candidates by optional scores, and writing selected_symbols back to config.json."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Config path relative to run_dir, usually config.json"},
            "candidate_symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Candidate symbols to consider; defaults to config.codes",
            },
            "symbol_scores": {
                "type": "object",
                "description": "Optional symbol -> score mapping used to rank candidates descending",
                "additionalProperties": {"type": "number"},
            },
            "max_positions": {
                "type": "integer",
                "description": "Maximum number of symbols to keep; defaults to config.max_positions or all candidates",
            },
            "exclude_symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Symbols to remove before ranking",
            },
            "selection_reason": {
                "type": "string",
                "description": "Short audit note explaining why these symbols were chosen",
            },
        },
        "required": ["path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for select_orchestrator_symbols"}, ensure_ascii=False)

        result = select_orchestrator_symbols(
            kwargs["path"],
            run_dir=run_dir,
            candidate_symbols=kwargs.get("candidate_symbols"),
            symbol_scores=kwargs.get("symbol_scores"),
            max_positions=kwargs.get("max_positions"),
            exclude_symbols=kwargs.get("exclude_symbols"),
            selection_reason=kwargs.get("selection_reason"),
        )
        return json.dumps(result, ensure_ascii=False)
