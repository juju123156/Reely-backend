"""Tool: execute or simulate broker orders from execution_plan.json."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.live_executor import execute_broker_plan


class ExecuteBrokerPlanTool(BaseTool):
    name = "execute_broker_plan"
    description = (
        "Read artifacts/execution_plan.json and artifacts/trade_decision.json, "
        "then simulate or execute orders through a configured broker adapter."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to the run directory"},
            "broker_name": {"type": "string", "description": "Optional broker override, e.g. kis or kiwoom"},
            "confirm_live": {"type": "boolean", "description": "Must be true to allow live mode execution"},
            "dry_run": {"type": "boolean", "description": "Force dry run even in live mode"},
        },
        "required": ["run_dir"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        result = execute_broker_plan(
            kwargs["run_dir"],
            broker_name=kwargs.get("broker_name"),
            confirm_live=bool(kwargs.get("confirm_live", False)),
            dry_run=kwargs.get("dry_run"),
        )
        return json.dumps(result, ensure_ascii=False)
