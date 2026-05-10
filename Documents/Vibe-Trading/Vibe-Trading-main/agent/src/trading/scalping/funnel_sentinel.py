"""Report-only buy funnel sentinel.

The sentinel diagnoses droughts and blockers.  It must never mutate thresholds
or live trading parameters.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta
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


def build_buy_funnel_sentinel_report(
    *,
    report_date: date | None = None,
    diagnostics_dir: str | Path = "data/strategy_diagnostics",
    pipeline_dir: str | Path = "data/pipeline_events",
    output_dir: str | Path = "data/sentinels",
    window_minutes: int = 30,
) -> dict[str, Any]:
    day = (report_date or date.today()).isoformat()
    diag_rows = _read_jsonl(Path(diagnostics_dir) / f"{day}.jsonl")
    pipe_rows = _read_jsonl(Path(pipeline_dir) / f"{day}.jsonl")
    rows = diag_rows + pipe_rows
    cutoff = datetime.now() - timedelta(minutes=window_minutes)

    def in_window(row: dict[str, Any]) -> bool:
        raw = row.get("timestamp") or row.get("recorded_at")
        if not raw:
            return True
        try:
            return datetime.fromisoformat(str(raw)) >= cutoff
        except ValueError:
            return True

    recent = [r for r in rows if in_window(r)]
    route = [r for r in recent if r.get("event_type") == "route_summary"]
    signals = [r for r in recent if r.get("event_type") in {"strategy_signal", "signal_generated"}]
    shadow = [r for r in recent if r.get("event_type") == "shadow_entry"]
    orders = [r for r in recent if r.get("event_type") == "live_order_attempt"]
    fills = [r for r in recent if r.get("event_type") == "live_order_fill"]
    rejects = [r for r in recent if r.get("event_type") in {"strategy_reject", "entry_policy_reject"}]

    last_route = route[-1] if route else {}
    top_reject = Counter(str(r.get("reject_reason") or r.get("terminal_blocker") or "unknown") for r in rejects)
    terminal = top_reject.most_common(1)[0][0] if top_reject else ""
    recommendation = "normal"
    if last_route and int(last_route.get("raw_scan_count") or 0) > 0 and not signals:
        recommendation = "inspect_strategy_candidate_to_signal"
    if signals and not orders:
        recommendation = "inspect_promotion_runtime_execution_risk_gates"
    if orders and not fills:
        recommendation = "inspect_order_timeout_fill_slippage"

    report = {
        "event_type": "buy_funnel_sentinel_report",
        "generated_at": datetime.now().isoformat(),
        "date": day,
        "window_minutes": window_minutes,
        "raw_scan_count": int(last_route.get("raw_scan_count") or 0),
        "route_candidate_count": sum((last_route.get("strategy_candidate_count_by_strategy") or {}).values()),
        "strategy_signal_count": len(signals),
        "shadow_entry_count": len(shadow),
        "live_order_count": len(orders),
        "fill_count": len(fills),
        "top_terminal_blocker": terminal,
        "top_reject_reason": dict(top_reject.most_common(20)),
        "stale_quote_ratio": _ratio(rejects, {"stale_quote", "stale_tick", "stale_feature", "stale_orderbook"}),
        "runtime_block_ratio": _ratio(rejects, {"runtime_permission_blocked", "regime_no_trade", "regime_confirming"}),
        "promotion_block_ratio": _ratio(rejects, {"promotion_gate_shadow_only"}),
        "recommended_check": recommendation,
        "report_only": True,
    }
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"buy_funnel_{day}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def _ratio(rows: list[dict[str, Any]], reasons: set[str]) -> float:
    if not rows:
        return 0.0
    hits = 0
    for row in rows:
        reason = str(row.get("reject_reason") or row.get("terminal_blocker") or "")
        if reason in reasons:
            hits += 1
    return hits / len(rows)
