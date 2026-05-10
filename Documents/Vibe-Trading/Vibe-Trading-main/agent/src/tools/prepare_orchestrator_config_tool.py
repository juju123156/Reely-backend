"""Tool: standardize config.json for orchestrator-managed KR strategy workflows."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.orchestrator_runner import prepare_orchestrator_config


class PrepareOrchestratorConfigTool(BaseTool):
    """Prepare config.json with orchestrator fields before strategy backtest."""

    name = "prepare_orchestrator_config"
    description = (
        "Update config.json for orchestrator workflows by setting mode, selected_symbols, "
        "strategy metadata, and KR intraday exit_policy defaults."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Config path relative to run_dir, usually config.json"},
            "mode": {"type": "string", "description": "research, paper, or live"},
            "selected_symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Candidate symbols selected by the orchestrator for the next decision step",
            },
            "strategy_id": {"type": "string", "description": "Stable strategy identifier"},
            "strategy_version": {"type": "string", "description": "Strategy version label"},
            "signal_exit": {"type": "string"},
            "stop_loss": {"type": "string"},
            "take_profit": {"type": "string"},
            "time_stop": {"type": "string"},
            "fallback_rule": {"type": "string"},
        },
        "required": ["path", "mode"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for prepare_orchestrator_config"}, ensure_ascii=False)

        result = prepare_orchestrator_config(
            kwargs["path"],
            run_dir=run_dir,
            mode=kwargs.get("mode", "research"),
            selected_symbols=kwargs.get("selected_symbols"),
            strategy_id=kwargs.get("strategy_id"),
            strategy_version=kwargs.get("strategy_version"),
            signal_exit=kwargs.get("signal_exit"),
            stop_loss=kwargs.get("stop_loss"),
            take_profit=kwargs.get("take_profit"),
            time_stop=kwargs.get("time_stop"),
            fallback_rule=kwargs.get("fallback_rule"),
        )
        return json.dumps(result, ensure_ascii=False)
