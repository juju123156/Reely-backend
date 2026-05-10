"""JSONL persistence for CLOSE_BET performance analysis."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


class ClosingBetResultStore:
    def __init__(self, base_dir: str | Path = "data/closing_bet_results") -> None:
        self._base_dir = Path(base_dir)

    def append(self, record: dict[str, Any], trade_date: date | None = None) -> Path:
        day = trade_date or date.today()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._base_dir / f"{day.isoformat()}.jsonl"
        payload = {
            "date": day.isoformat(),
            "position_type": "close_bet",
            "holding_overnight": True,
            **record,
        }
        if "weekday" not in payload:
            payload["weekday"] = datetime.now().strftime("%a")
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return path


def gap_pct(entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (exit_price - entry_price) / entry_price


def net_pnl_after_costs(
    entry_price: float,
    exit_price: float,
    qty: int,
    commission: float,
    tax: float,
) -> float:
    return (exit_price - entry_price) * qty - commission - tax
