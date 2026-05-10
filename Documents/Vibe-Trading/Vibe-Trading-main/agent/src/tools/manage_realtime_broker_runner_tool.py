"""Tool: start/stop/check background realtime broker runners."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.realtime_runner import get_realtime_runner_manager


class ManageRealtimeBrokerRunnerTool(BaseTool):
    name = "manage_realtime_broker_runner"
    description = (
        "Start, stop, or inspect a background realtime broker runner that "
        "uses websocket quote updates to refresh selected_symbols."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "task_id": {"type": "string"},
            "broker_name": {"type": "string"},
            "run_dir": {"type": "string"},
            "path": {"type": "string"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "market_code": {"type": "string"},
            "quote_types": {"type": "array", "items": {"type": "string"}},
            "score_field": {"type": "string"},
            "max_positions": {"type": "integer"},
            "selection_reason": {"type": "string"},
            "poll_interval": {"type": "number"},
            "env_dv": {"type": "string"},
            "max_cycles": {"type": "integer"},
        },
        "required": ["action"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        manager = get_realtime_runner_manager()
        action = str(kwargs["action"]).strip().lower()
        if action == "start":
            result = manager.start(
                broker_name=str(kwargs.get("broker_name") or "kiwoom"),
                run_dir=str(kwargs.get("run_dir") or ""),
                path=str(kwargs.get("path") or "config.json"),
                symbols=list(kwargs.get("symbols") or []),
                market_code=str(kwargs.get("market_code") or "KRX"),
                quote_types=list(kwargs.get("quote_types") or ["0B"]),
                score_field=str(kwargs.get("score_field") or "flu_rt"),
                max_positions=kwargs.get("max_positions"),
                selection_reason=str(kwargs.get("selection_reason") or ""),
                poll_interval=float(kwargs.get("poll_interval") or 5.0),
                env_dv=kwargs.get("env_dv"),
                max_cycles=kwargs.get("max_cycles"),
            )
        elif action == "stop":
            result = manager.stop(str(kwargs.get("task_id") or ""))
        elif action in {"status", "list"}:
            result = manager.status(kwargs.get("task_id"))
        else:
            result = {"status": "error", "error": "unsupported action"}
        return json.dumps(result, ensure_ascii=False)
