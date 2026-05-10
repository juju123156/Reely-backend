"""Helper tool: ensure KR intraday paper/live configs have a fallback exit policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_path as _safe_path
from src.trading.paper_state import (
    extract_exit_policy,
    requires_explicit_exit_guard,
)


DEFAULT_EXIT_POLICY = {
    "signal_exit": "20EMA breakdown or VWAP breakdown",
    "stop_loss": "-1.2%",
    "take_profit": "+2.5%",
    "time_stop": "15:20 force exit",
    "fallback_rule": "if no signal then time_stop",
}


def ensure_exit_policy(path: str, *, run_dir: str, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    resolved = _safe_path(path, Path(run_dir))
    if not resolved.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    try:
        config = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"config.json parse error: {exc}"}

    if not isinstance(config, dict):
        return {"status": "error", "error": "config must be a JSON object"}

    if not requires_explicit_exit_guard(config):
        return {
            "status": "ok",
            "path": str(resolved),
            "updated": False,
            "message": "explicit exit guard not required for this config",
        }

    current = extract_exit_policy(config)
    merged = dict(DEFAULT_EXIT_POLICY)
    if overrides:
        merged.update({k: str(v) for k, v in overrides.items() if v})
    merged.update({k: v for k, v in current.items() if v})

    existing = config.get("exit_policy")
    if not isinstance(existing, dict):
        existing = {}
    new_policy = {**existing, **merged}
    changed = new_policy != existing

    config["exit_policy"] = new_policy
    if changed:
        resolved.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "path": str(resolved),
        "updated": changed,
        "exit_policy": new_policy,
    }


class EnsureExitPolicyTool(BaseTool):
    """Ensure `config.json` contains a complete exit policy when required."""

    name = "ensure_exit_policy"
    description = (
        "Read config.json and auto-fill missing KR intraday paper/live exit_policy "
        "fields (stop_loss, take_profit, time_stop, fallback_rule)."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Config path relative to run_dir, usually config.json",
            },
            "signal_exit": {"type": "string", "description": "Optional override for signal_exit"},
            "stop_loss": {"type": "string", "description": "Optional override for stop_loss"},
            "take_profit": {"type": "string", "description": "Optional override for take_profit"},
            "time_stop": {"type": "string", "description": "Optional override for time_stop"},
            "fallback_rule": {"type": "string", "description": "Optional override for fallback_rule"},
        },
        "required": ["path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        run_dir = kwargs.get("run_dir")
        if not run_dir:
            return json.dumps({"status": "error", "error": "run_dir is required for ensure_exit_policy"}, ensure_ascii=False)

        overrides = {
            "signal_exit": kwargs.get("signal_exit"),
            "stop_loss": kwargs.get("stop_loss"),
            "take_profit": kwargs.get("take_profit"),
            "time_stop": kwargs.get("time_stop"),
            "fallback_rule": kwargs.get("fallback_rule"),
        }
        result = ensure_exit_policy(kwargs["path"], run_dir=run_dir, overrides=overrides)
        return json.dumps(result, ensure_ascii=False)
