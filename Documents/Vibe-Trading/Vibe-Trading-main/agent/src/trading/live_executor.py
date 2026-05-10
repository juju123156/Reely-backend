"""Paper/live broker execution scaffold."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.brokers import get_broker_adapter
from src.brokers.base import BrokerOrderRequest
from src.trading.broker_feedback import sync_broker_feedback


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def execute_broker_plan(
    run_dir: str,
    *,
    broker_name: str | None = None,
    confirm_live: bool = False,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    plan_path = run_path / "artifacts" / "execution_plan.json"
    decision_path = run_path / "artifacts" / "trade_decision.json"
    if not plan_path.exists():
        return {"status": "error", "error": "execution_plan.json not found"}
    if not decision_path.exists():
        return {"status": "error", "error": "trade_decision.json not found"}

    plan = _load_json(plan_path)
    decision = _load_json(decision_path)
    mode = str(plan.get("mode") or decision.get("mode") or "research").strip().lower()
    broker = str(broker_name or plan.get("broker") or "").strip().lower()
    if not broker:
        return {"status": "error", "error": "broker is not set in execution_plan.json"}
    if not bool(plan.get("ready")):
        return {"status": "error", "error": "execution plan is not ready", "plan_ready": False}
    if decision.get("decision") == "HOLD":
        return {"status": "error", "error": "trade decision is HOLD"}
    if mode == "live" and not confirm_live:
        return {
            "status": "error",
            "error": "live execution requires confirm_live=true",
            "approval_required": True,
        }

    use_dry_run = dry_run if dry_run is not None else (mode != "live")
    adapter = get_broker_adapter(broker)
    connection = adapter.check_connection()
    if connection.get("status") == "error":
        return {
            "status": "error",
            "error": "broker connection check failed",
            "connection": connection,
        }

    results = []
    for order in plan.get("orders") or []:
        request = BrokerOrderRequest(
            symbol=str(order.get("symbol") or ""),
            side=str(order.get("side") or "NONE"),
            qty_policy=str(order.get("qty_policy") or ""),
            limit_policy=str(order.get("limit_policy") or ""),
            time_in_force=str(order.get("time_in_force") or "DAY"),
            quantity=float(order["quantity"]) if order.get("quantity") is not None else None,
            limit_price=float(order["limit_price"]) if order.get("limit_price") is not None else None,
            metadata={
                "selection_score": order.get("selection_score"),
                "market_code": order.get("market_code"),
                "order_type": order.get("order_type"),
                "conditional_price": order.get("conditional_price"),
                "strategy_id": decision.get("strategy_id", ""),
                "strategy_version": decision.get("strategy_version", ""),
                "entry_signal_snapshot": plan.get("entry_signal_snapshot") or {},
                "exit_policy_snapshot": plan.get("exit_policy_snapshot") or {},
            },
        )
        results.append(adapter.place_order(request, mode=mode, dry_run=use_dry_run).to_dict())

    payload = {
        "generated_at": _now_iso(),
        "broker": broker,
        "mode": mode,
        "dry_run": use_dry_run,
        "confirm_live": confirm_live,
        "results": results,
        "connection": connection,
    }
    out_path = run_path / "artifacts" / "broker_execution_result.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    orders_snapshot: dict[str, Any] = {}
    fills_snapshot: dict[str, Any] = {}
    try:
        orders_snapshot = adapter.get_orders()
    except Exception as exc:
        orders_snapshot = {"status": "error", "error": str(exc)}
    try:
        fills_snapshot = adapter.get_fills()
    except Exception as exc:
        fills_snapshot = {"status": "error", "error": str(exc)}

    feedback = sync_broker_feedback(
        run_path,
        broker=broker,
        execution_result=payload,
        orders=orders_snapshot,
        fills=fills_snapshot,
    )
    return {
        "status": "ok",
        "artifact": str(out_path),
        "broker_feedback_artifact": feedback.get("artifact", ""),
        "orders_snapshot": orders_snapshot,
        "fills_snapshot": fills_snapshot,
        **payload,
    }
