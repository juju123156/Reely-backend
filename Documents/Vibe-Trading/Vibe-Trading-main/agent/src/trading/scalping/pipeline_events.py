"""Unified pipeline event logging for scalping diagnostics.

This module is deliberately small and side-effect limited: it only writes JSONL
events so existing trading decisions are not changed by observability work.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PipelineEvent:
    record_id: str
    symbol: str
    stage: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    name: str = ""
    strategy: str = ""
    accepted: bool = False
    reject_reason: str = ""
    terminal_blocker: str = ""
    regime: str = ""
    promotion_state: str = ""
    runtime_permission: str = ""
    current_price: float = 0.0
    expected_entry_price: float = 0.0
    spread_pct: float = 0.0
    quote_age_ms: float = 0.0
    tick_age_ms: float = 0.0
    feature_age_ms: float = 0.0
    depth_levels_available: int = 0
    orderbook_age_sec: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["event_type"] = "pipeline_event"
        return row


def make_record_id(symbol: str, strategy: str = "", seed: str | None = None) -> str:
    safe_symbol = str(symbol or "unknown")
    safe_strategy = str(strategy or "unknown")
    suffix = seed or str(int(time.time() * 1000))
    return f"{date.today().isoformat()}:{safe_symbol}:{safe_strategy}:{suffix}"


class PipelineEventLogger:
    def __init__(self, base_dir: str | Path = "data/pipeline_events") -> None:
        self._base_dir = Path(base_dir)

    def append(self, event: PipelineEvent | dict[str, Any]) -> dict[str, Any]:
        row = event.to_dict() if isinstance(event, PipelineEvent) else dict(event)
        row.setdefault("event_type", "pipeline_event")
        row.setdefault("timestamp", datetime.now().isoformat())
        path = self._base_dir / f"{date.today().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return row


def event_from_diagnostic(
    *,
    record_id: str,
    stage: str,
    payload: dict[str, Any],
    accepted: bool = False,
    terminal_blocker: str = "",
) -> PipelineEvent:
    metrics = payload.get("metrics") or {}
    return PipelineEvent(
        record_id=record_id,
        symbol=str(payload.get("symbol") or metrics.get("symbol") or ""),
        name=str(payload.get("name") or metrics.get("name") or ""),
        strategy=str(payload.get("strategy") or metrics.get("strategy") or ""),
        stage=stage,
        accepted=bool(payload.get("accepted", accepted)),
        reject_reason=str(payload.get("reject_reason") or ""),
        terminal_blocker=terminal_blocker or str(payload.get("reject_reason") or ""),
        regime=str(payload.get("market_regime") or payload.get("active_market_regime") or ""),
        promotion_state=str(metrics.get("promotion_state") or payload.get("promotion_state") or ""),
        runtime_permission=str(metrics.get("runtime_permission") or payload.get("runtime_permission") or ""),
        current_price=float(metrics.get("price") or metrics.get("current_price") or 0.0),
        expected_entry_price=float(metrics.get("expected_entry_price") or payload.get("expected_entry_price") or 0.0),
        spread_pct=float(metrics.get("spread_pct") or payload.get("spread_pct") or 0.0),
        quote_age_ms=float(metrics.get("quote_age_ms") or payload.get("quote_age_ms") or 0.0),
        tick_age_ms=float(metrics.get("tick_age_ms") or payload.get("tick_age_ms") or 0.0),
        feature_age_ms=float(metrics.get("feature_age_ms") or payload.get("feature_age_ms") or 0.0),
        depth_levels_available=int(metrics.get("depth_levels_available") or payload.get("depth_levels_available") or 0),
        orderbook_age_sec=float(metrics.get("orderbook_age_sec") or payload.get("orderbook_age_sec") or 0.0),
        payload=payload,
    )
