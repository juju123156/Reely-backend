"""Operational alert sink for live trading safety events."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertEvent:
    kind: str
    severity: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class OperationalAlertSink:
    """Writes every alert locally and optionally forwards to a webhook.

    Set TRADING_ALERT_WEBHOOK_URL to a Slack/Telegram relay webhook.  The local
    JSONL write is always enabled so alert behavior remains auditable even when
    external notification credentials are absent.
    """

    def __init__(self, base_dir: str | Path = "data/alerts", webhook_url: str | None = None) -> None:
        self._base_dir = Path(base_dir)
        self._webhook_url = webhook_url if webhook_url is not None else os.getenv("TRADING_ALERT_WEBHOOK_URL", "")

    def emit(self, event: AlertEvent) -> None:
        row = {
            "timestamp": datetime.now().isoformat(),
            "kind": event.kind,
            "severity": event.severity,
            "message": event.message,
            "payload": event.payload,
        }
        self._write_local(row)
        logger.warning("[Alert:%s] %s payload=%s", event.kind, event.message, event.payload)
        if self._webhook_url:
            self._send_webhook(row)

    def _write_local(self, row: dict[str, Any]) -> None:
        path = self._base_dir / f"{date.today().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def _send_webhook(self, row: dict[str, Any]) -> None:
        body = json.dumps({"text": f"[{row['severity']}] {row['kind']}: {row['message']}", "payload": row}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=1.0).close()
        except Exception as exc:
            logger.warning("alert webhook failed: %s", exc)
