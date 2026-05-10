"""CLOSE_BET 전략 전용 진단 리포트.

shadow_trading 로그 + closing_bet_results를 집계하여
오버나이트 gap 분포, 익일 오픈 체결 성공률, 비용 후 순기대값을 출력한다.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median, stdev
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


def _pct_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "mean": round(mean(values), 5),
        "median": round(median(values), 5),
        "stdev": round(stdev(values), 5) if len(values) > 1 else 0.0,
        "min": round(min(values), 5),
        "max": round(max(values), 5),
    }


def build_close_bet_diagnostics(
    *,
    report_date: date | None = None,
    closing_bet_results_dir: str | Path = "data/closing_bet_results",
    shadow_dir: str | Path = "data/shadow_trading",
    output_dir: str | Path = "data/close_bet_diagnostics",
    lookback_days: int = 30,
) -> dict[str, Any]:
    """지난 lookback_days 일간 CLOSE_BET 성과를 집계."""
    day = report_date or date.today()

    # closing_bet_results: 실제 체결된 종가베팅 결과
    bet_rows: list[dict[str, Any]] = []
    for i in range(lookback_days):
        from datetime import timedelta
        d = (datetime.combine(day, datetime.min.time()) - timedelta(days=i)).date()
        bet_rows.extend(_read_jsonl(Path(closing_bet_results_dir) / f"{d.isoformat()}.jsonl"))

    # shadow_trading: shadow/rejected close_bet candidates
    shadow_rows: list[dict[str, Any]] = []
    for i in range(lookback_days):
        from datetime import timedelta
        d = (datetime.combine(day, datetime.min.time()) - timedelta(days=i)).date()
        shadow_rows.extend(_read_jsonl(Path(shadow_dir) / f"{d.isoformat()}.jsonl"))

    shadow_close_bets = [
        r for r in shadow_rows
        if r.get("strategy") in {"close_bet", "closing_bet", "CLOSE_BET"}
    ]

    # ── Closed trade stats ────────────────────────────────────────────────────
    gap_pcts: list[float] = []
    net_pnls: list[float] = []
    weekday_gaps: dict[str, list[float]] = defaultdict(list)
    win_count = 0
    loss_count = 0
    timeout_count = 0

    for row in bet_rows:
        gp = float(row.get("gap_pct") or row.get("exit_gap_pct") or 0.0)
        net = float(row.get("net_pnl_pct") or row.get("net_pnl") or 0.0)
        gap_pcts.append(gp)
        net_pnls.append(net)
        wd = str(row.get("weekday") or "")
        if wd:
            weekday_gaps[wd].append(gp)
        if net > 0:
            win_count += 1
        elif net < 0:
            loss_count += 1
        if row.get("exit_reason") in {"deadline_force", "next_open_timeout"}:
            timeout_count += 1

    total_trades = win_count + loss_count
    win_rate = win_count / total_trades if total_trades > 0 else 0.0

    # ── Shadow candidate stats ────────────────────────────────────────────────
    shadow_entries = [r for r in shadow_close_bets if r.get("event_type") == "shadow_entry"]
    shadow_rejects = [r for r in shadow_close_bets if r.get("event_type") == "rejected_candidate_scan"]
    shadow_mfe_windows = [r for r in shadow_close_bets if "mfe_pct" in r and r.get("event_type", "").startswith("rejected_candidate_window")]

    shadow_mfes = [float(r["mfe_pct"]) for r in shadow_mfe_windows if r.get("mfe_pct") is not None]
    shadow_maes = [float(r["mae_pct"]) for r in shadow_mfe_windows if r.get("mae_pct") is not None]

    reject_reasons = Counter(str(r.get("reject_reason") or "unknown") for r in shadow_rejects)

    # ── Promotion readiness ───────────────────────────────────────────────────
    promotion_ready = False
    promotion_reason = "insufficient_data"
    if total_trades >= 20 and win_rate >= 0.50 and sum(net_pnls) > 0:
        promotion_ready = True
        promotion_reason = "net_positive_20_trades"
    elif total_trades < 10:
        promotion_reason = f"need_more_trades ({total_trades}/20)"

    report = {
        "event_type": "close_bet_diagnostics",
        "generated_at": datetime.now().isoformat(),
        "report_date": day.isoformat(),
        "lookback_days": lookback_days,
        # ── Live trade stats
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 4),
        "timeout_to_force_exit_count": timeout_count,
        "gap_pct_stats": _pct_stats(gap_pcts),
        "net_pnl_pct_stats": _pct_stats(net_pnls),
        "gap_pct_by_weekday": {wd: _pct_stats(vals) for wd, vals in weekday_gaps.items()},
        # ── Shadow stats
        "shadow_entry_count": len(shadow_entries),
        "shadow_reject_count": len(shadow_rejects),
        "shadow_mfe_stats": _pct_stats(shadow_mfes),
        "shadow_mae_stats": _pct_stats(shadow_maes),
        "top_reject_reasons": dict(reject_reasons.most_common(10)),
        # ── Promotion readiness
        "promotion_ready": promotion_ready,
        "promotion_reason": promotion_reason,
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"close_bet_diagnostics_{day.isoformat()}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return report
