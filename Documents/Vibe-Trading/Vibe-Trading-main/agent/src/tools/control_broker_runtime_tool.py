"""Tool: broker runtime control for order/fill/websocket workflows."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.brokers import get_broker_adapter
from src.trading.realtime_selection import apply_realtime_selection_update, update_realtime_selection_from_file


class ControlBrokerRuntimeTool(BaseTool):
    name = "control_broker_runtime"
    description = (
        "Control broker runtime actions such as modify/cancel order, "
        "order/fill lookup, websocket quote subscription, and Kiwoom condition search."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "broker_name": {"type": "string"},
            "action": {"type": "string"},
            "order_id": {"type": "string"},
            "symbol": {"type": "string"},
            "quantity": {"type": "number"},
            "limit_price": {"type": "number"},
            "limit_policy": {"type": "string"},
            "market_code": {"type": "string"},
            "env_dv": {"type": "string"},
            "filters": {"type": "object"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "quote_types": {"type": "array", "items": {"type": "string"}},
            "seq": {"type": "string"},
            "realtime": {"type": "boolean"},
            "timeout": {"type": "number"},
            "run_dir": {"type": "string"},
            "path": {"type": "string"},
            "messages": {"type": ["array", "object"]},
            "message_path": {"type": "string"},
            "score_field": {"type": "string"},
            "max_positions": {"type": "integer"},
            "selection_reason": {"type": "string"},
        },
        "required": ["broker_name", "action"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        broker = get_broker_adapter(str(kwargs["broker_name"]))
        action = str(kwargs["action"]).strip().lower()
        if action == "modify_order":
            result = broker.modify_order(
                str(kwargs.get("order_id") or ""),
                symbol=str(kwargs.get("symbol") or ""),
                quantity=kwargs.get("quantity"),
                limit_price=kwargs.get("limit_price"),
                market_code=str(kwargs.get("market_code") or "KRX"),
                limit_policy=str(kwargs.get("limit_policy") or ""),
                env_dv=kwargs.get("env_dv"),
            )
        elif action == "cancel_order":
            result = broker.cancel_order(
                str(kwargs.get("order_id") or ""),
                symbol=str(kwargs.get("symbol") or ""),
                quantity=kwargs.get("quantity"),
                market_code=str(kwargs.get("market_code") or "KRX"),
                env_dv=kwargs.get("env_dv"),
            )
        elif action == "get_orders":
            result = broker.get_orders(env_dv=kwargs.get("env_dv"), filters=kwargs.get("filters"))
        elif action == "get_fills":
            result = broker.get_fills(env_dv=kwargs.get("env_dv"), filters=kwargs.get("filters"))
        elif action == "build_quote_subscription":
            result = broker.build_quote_subscription(
                kwargs.get("symbols") or [],
                quote_types=kwargs.get("quote_types"),
                market_code=str(kwargs.get("market_code") or "KRX"),
            )
        elif action == "list_conditions":
            result = broker.list_conditions(env_dv=kwargs.get("env_dv"), timeout=float(kwargs.get("timeout") or 5.0))
        elif action == "run_condition_search":
            result = broker.run_condition_search(
                str(kwargs.get("seq") or ""),
                realtime=bool(kwargs.get("realtime", False)),
                env_dv=kwargs.get("env_dv"),
                timeout=float(kwargs.get("timeout") or 5.0),
            )
        elif action == "release_condition_search":
            result = broker.release_condition_search(
                str(kwargs.get("seq") or ""),
                env_dv=kwargs.get("env_dv"),
                timeout=float(kwargs.get("timeout") or 5.0),
            )
        elif action == "apply_realtime_selection":
            result = apply_realtime_selection_update(
                str(kwargs.get("path") or "config.json"),
                run_dir=str(kwargs.get("run_dir") or ""),
                messages=kwargs.get("messages") or [],
                score_field=str(kwargs.get("score_field") or "flu_rt"),
                max_positions=kwargs.get("max_positions"),
                selection_reason=str(kwargs.get("selection_reason") or ""),
            )
        elif action == "apply_realtime_selection_from_file":
            result = update_realtime_selection_from_file(
                str(kwargs.get("path") or "config.json"),
                run_dir=str(kwargs.get("run_dir") or ""),
                message_path=str(kwargs.get("message_path") or ""),
                score_field=str(kwargs.get("score_field") or "flu_rt"),
                max_positions=kwargs.get("max_positions"),
                selection_reason=str(kwargs.get("selection_reason") or ""),
            )
        else:
            result = {"status": "error", "error": "unsupported action"}
        return json.dumps(result, ensure_ascii=False)
