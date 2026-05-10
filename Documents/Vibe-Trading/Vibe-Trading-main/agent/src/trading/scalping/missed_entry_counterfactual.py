"""Classify rejected candidates by post-reject MFE/MAE outcome."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


MISSED_WINNER = "MISSED_WINNER"
AVOIDED_LOSER = "AVOIDED_LOSER"
NEUTRAL = "NEUTRAL"
UNKNOWN_DATA = "UNKNOWN_DATA"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def classify_window(row: dict[str, Any]) -> str:
    if not row:
        return UNKNOWN_DATA
    mfe = float(row.get("mfe_pct") or 0.0)
    mae = float(row.get("mae_pct") or 0.0)
    net = float(row.get("net_expectancy") or row.get("net_mfe_pct") or 0.0)
    if mfe >= 0.010 and mae >= -0.006 and net > 0:
        return MISSED_WINNER
    if mae <= -0.008 or (mfe < 0.004 and mae < -0.004):
        return AVOIDED_LOSER
    return NEUTRAL


def build_missed_entry_counterfactual(
    *,
    report_date: date | None = None,
    shadow_dir: str | Path = "data/shadow_trading",
    output_dir: str | Path = "data/strategy_reports",
) -> dict[str, Any]:
    day = (report_date or date.today()).isoformat()
    rows = _read_jsonl(Path(shadow_dir) / f"{day}.jsonl")
    windows = [
        r for r in rows
        if r.get("event_type") in {"rejected_candidate_window_5m", "rejected_candidate_window"}
        and int(r.get("window_sec") or 0) == 300
    ]
    classified: list[dict[str, Any]] = []
    by_blocker: dict[str, Counter] = defaultdict(Counter)
    by_strategy: dict[str, Counter] = defaultdict(Counter)
    by_regime: dict[str, Counter] = defaultdict(Counter)
    by_time_bucket: dict[str, Counter] = defaultdict(Counter)
    for row in windows:
        outcome = classify_window(row)
        item = {
            "event_type": "missed_entry_counterfactual",
            "timestamp": datetime.now().isoformat(),
            "event_id": row.get("event_id"),
            "record_id": row.get("record_id") or row.get("event_id"),
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "strategy": row.get("strategy"),
            "terminal_blocker": row.get("reject_reason") or "unknown",
            "reject_reason": row.get("reject_reason") or "unknown",
            "window_sec": row.get("window_sec"),
            "mfe_pct": row.get("mfe_pct"),
            "mae_pct": row.get("mae_pct"),
            "net_expectancy": row.get("net_expectancy"),
            "classification": outcome,
            "time_bucket": row.get("time_bucket") or "",
            "regime": row.get("regime") or "",
        }
        classified.append(item)
        by_blocker[str(item["terminal_blocker"])][outcome] += 1
        by_strategy[str(item["strategy"])][outcome] += 1
        by_regime[str(item["regime"])][outcome] += 1
        by_time_bucket[str(item["time_bucket"])][outcome] += 1

    report = {
        "event_type": "blocker_outcome_summary",
        "generated_at": datetime.now().isoformat(),
        "date": day,
        "sample_count": len(classified),
        "overall": dict(Counter(i["classification"] for i in classified)),
        "terminal_blocker": {k: dict(v) for k, v in by_blocker.items()},
        "strategy": {k: dict(v) for k, v in by_strategy.items()},
        "regime": {k: dict(v) for k, v in by_regime.items()},
        "time_bucket": {k: dict(v) for k, v in by_time_bucket.items()},
    }
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"missed_entry_counterfactual_{day}.json").write_text(
        json.dumps({"report": report, "items": classified}, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return report
