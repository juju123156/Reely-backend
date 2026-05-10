"""Report-only holding/exit diagnostics.

This module surfaces exit candidates but does not mutate live exit policy.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any


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


def build_holding_exit_sentinel_report(
    *,
    report_date: date | None = None,
    diagnostics_dir: str | Path = "data/strategy_diagnostics",
    output_dir: str | Path = "data/sentinels",
) -> dict[str, Any]:
    day = (report_date or date.today()).isoformat()
    rows = _read_jsonl(Path(diagnostics_dir) / f"{day}.jsonl")
    fills = [r for r in rows if r.get("event_type") == "live_order_fill" and r.get("side") == "buy"]
    exits = [r for r in rows if r.get("event_type") == "live_order_fill" and r.get("side") == "sell"]
    stability = [r for r in rows if r.get("event_type") == "orderbook_stability_snapshot"]
    micro = [r for r in rows if r.get("event_type") == "microprice_snapshot"]
    reasons = Counter()
    if stability:
        latest = stability[-1]
        if float(latest.get("microprice_edge") or 0.0) < 0:
            reasons["microprice_worsening"] += 1
        if float(latest.get("orderbook_flicker_rate") or 0.0) > 0.5:
            reasons["orderbook_flicker_high"] += 1
    if micro:
        latest_micro = micro[-1]
        if float(latest_micro.get("aggressive_sell_ratio") or 0.0) >= 0.65:
            reasons["aggressive_sell_spike"] += 1
        if bool(latest_micro.get("blocked")):
            reasons[str(latest_micro.get("block_reason") or "microprice_blocked")] += 1

    report = {
        "event_type": "holding_exit_sentinel_report",
        "generated_at": datetime.now().isoformat(),
        "date": day,
        "open_entry_count_estimate": max(0, len(fills) - len(exits)),
        "buy_fill_count": len(fills),
        "sell_fill_count": len(exits),
        "suggested_exit_reasons": dict(reasons.most_common(20)),
        "time_stop_candidate": False,
        "vwap_break_candidate": False,
        "strength_decay_candidate": "aggressive_sell_spike" in reasons,
        "report_only": True,
    }
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"holding_exit_{day}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return report
