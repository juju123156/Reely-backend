"""Tool: fetch broker-backed quote or intraday bar data."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.brokers import get_broker_adapter


class ReadBrokerMarketDataTool(BaseTool):
    name = "read_broker_market_data"
    description = (
        "Fetch quote or intraday bar data through a configured broker adapter. "
        "Useful for KIS-backed Korean market validation before order execution."
    )
    is_readonly = True
    parameters = {
        "type": "object",
        "properties": {
            "broker_name": {"type": "string", "description": "Broker name, e.g. kis"},
            "action": {"type": "string", "description": "quote or intraday"},
            "symbol": {"type": "string", "description": "Ticker symbol, e.g. 005930.KS"},
            "interval": {"type": "string", "description": "1m, 5m, 15m, 30m, 1h"},
            "start": {"type": "string", "description": "Optional start time filter"},
            "end": {"type": "string", "description": "Optional end time filter"},
            "env_dv": {"type": "string", "description": "real or demo"},
            "market_code": {"type": "string", "description": "KIS market code, default J"},
        },
        "required": ["broker_name", "action", "symbol"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        broker = get_broker_adapter(str(kwargs["broker_name"]))
        action = str(kwargs["action"]).strip().lower()
        symbol = str(kwargs["symbol"]).strip()
        env_dv = kwargs.get("env_dv")
        market_code = str(kwargs.get("market_code") or "J").strip()
        if action == "quote":
            result = broker.get_quote(symbol, market_code=market_code, env_dv=env_dv)
            return json.dumps(result, ensure_ascii=False)
        if action == "intraday":
            result = broker.get_intraday_bars(
                symbol,
                str(kwargs.get("interval") or "1m"),
                str(kwargs.get("start") or ""),
                str(kwargs.get("end") or ""),
                env_dv=env_dv,
                market_code=market_code,
            )
            return json.dumps(result, ensure_ascii=False)
        return json.dumps(
            {"status": "error", "error": "action must be one of: quote, intraday"},
            ensure_ascii=False,
        )
