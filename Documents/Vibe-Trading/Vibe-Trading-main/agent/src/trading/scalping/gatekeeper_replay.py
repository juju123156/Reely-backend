"""Decision snapshot persistence and replay helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GatekeeperSnapshot:
    record_id: str
    symbol: str
    strategy: str
    final_decision: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    signal_score: float = 0.0
    leader_score: float = 0.0
    regime_score: float = 0.0
    promotion_state: str = ""
    runtime_permission: str = ""
    quote_health_state: str = ""
    latency_state: str = ""
    execution_quality_score: float = 0.0
    risk_state: str = ""
    terminal_blocker: str = ""
    blocker_reason: str = ""
    full_feature_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["event_type"] = "gatekeeper_snapshot"
        return row


class GatekeeperReplayStore:
    def __init__(self, base_dir: str | Path = "data/gatekeeper_replay") -> None:
        self._base_dir = Path(base_dir)

    def append(self, snapshot: GatekeeperSnapshot | dict[str, Any]) -> dict[str, Any]:
        row = snapshot.to_dict() if isinstance(snapshot, GatekeeperSnapshot) else dict(snapshot)
        row.setdefault("event_type", "gatekeeper_snapshot")
        row.setdefault("timestamp", datetime.now().isoformat())
        path = self._base_dir / f"{date.today().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return row

    def load(self, report_date: date | None = None) -> list[dict[str, Any]]:
        day = (report_date or date.today()).isoformat()
        path = self._base_dir / f"{day}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def replay(
        self,
        decide: Callable[[dict[str, Any]], str],
        *,
        report_date: date | None = None,
    ) -> list[dict[str, Any]]:
        mismatches: list[dict[str, Any]] = []
        for row in self.load(report_date):
            expected = str(row.get("final_decision") or "")
            actual = str(decide(row))
            if expected != actual:
                mismatch = {
                    "event_type": "gatekeeper_replay_mismatch",
                    "timestamp": datetime.now().isoformat(),
                    "record_id": row.get("record_id"),
                    "symbol": row.get("symbol"),
                    "strategy": row.get("strategy"),
                    "expected_decision": expected,
                    "actual_decision": actual,
                }
                self.append(mismatch)
                mismatches.append(mismatch)
        return mismatches
