"""Broker feedback synchronization helpers for execution history artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_broker_feedback(
    run_dir: str | Path,
    *,
    broker: str,
    execution_result: dict[str, Any] | None = None,
    orders: dict[str, Any] | None = None,
    fills: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    artifacts_dir = run_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": _now_iso(),
        "broker": broker,
        "execution_result": execution_result or {},
        "orders": orders or {},
        "fills": fills or {},
    }
    payload["open_order_count"] = len((orders or {}).get("orders") or [])
    payload["fill_count"] = len((fills or {}).get("fills") or [])

    feedback_path = artifacts_dir / "broker_feedback.json"
    feedback_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    history_path = artifacts_dir / "execution_history.json"
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            history = []
        if isinstance(history, list) and history:
            latest = history[-1]
            if isinstance(latest, dict):
                latest["broker"] = broker
                latest["broker_feedback_generated_at"] = payload["generated_at"]
                latest["broker_execution_result"] = execution_result or {}
                latest["broker_orders"] = orders or {}
                latest["broker_fills"] = fills or {}
                latest["open_order_count"] = payload["open_order_count"]
                latest["fill_count"] = payload["fill_count"]
                history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "artifact": str(feedback_path), **payload}
