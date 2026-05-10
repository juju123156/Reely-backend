"""Daily evidence report for shadow-first intraday promotion gates."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from .holding_exit_sentinel import build_holding_exit_sentinel_report
from .missed_entry_counterfactual import build_missed_entry_counterfactual
from .strategy_promotion import decide_promotions, write_promotion_state


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


def _strategy_key(row: dict[str, Any]) -> str:
    strategy = str(row.get("strategy") or "")
    if strategy.startswith("shadow_"):
        strategy = strategy.removeprefix("shadow_")
    if strategy == "leader_only":
        return "leader_only_shallow_pullback"
    if strategy == "score_70":
        return "leader_only_shallow_pullback"
    return strategy or "unknown"


def build_daily_strategy_report(
    *,
    report_date: date | None = None,
    shadow_dir: str | Path = "data/shadow_trading",
    diagnostics_dir: str | Path = "data/strategy_diagnostics",
    output_dir: str | Path = "data/strategy_reports",
    promotion_dir: str | Path = "data/strategy_promotion",
) -> dict[str, Any]:
    """Aggregate T-day evidence and update T+1 promotion state."""
    report_date = report_date or date.today()
    day = report_date.isoformat()
    shadow_rows = _read_jsonl(Path(shadow_dir) / f"{day}.jsonl")
    diag_rows = _read_jsonl(Path(diagnostics_dir) / f"{day}.jsonl")

    windows = [
        r for r in shadow_rows
        if str(r.get("event_type", "")).endswith("_window_5m")
    ]
    windows_30s = [
        r for r in shadow_rows
        if str(r.get("event_type", "")).endswith("_window_30s")
    ]
    trade_results = [
        r for r in shadow_rows + diag_rows
        if r.get("event_type") == "shadow_trade_result"
    ]
    expected_edges = [r for r in diag_rows if r.get("event_type") == "expected_edge_snapshot"]
    rejects = [r for r in diag_rows if r.get("event_type") == "strategy_reject"]
    route_summaries = [r for r in diag_rows if r.get("event_type") == "route_summary"]
    freshness = [r for r in diag_rows if r.get("event_type") == "feature_freshness"]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in windows:
        grouped[_strategy_key(row)].append(row)
    for row in trade_results:
        grouped[_strategy_key(row)].append(row)

    strategy_stats: dict[str, dict[str, Any]] = {}
    for strategy, rows in sorted(grouped.items()):
        mfes = [float(r.get("mfe_pct") or 0.0) for r in rows if "mfe_pct" in r]
        maes = [float(r.get("mae_pct") or 0.0) for r in rows if "mae_pct" in r]
        nets = [
            float(r.get("net_expectancy", r.get("net_pnl_after_cost_pct", 0.0)) or 0.0)
            for r in rows
            if ("net_expectancy" in r or "net_pnl_after_cost_pct" in r)
        ]
        wins = [v for v in nets if v > 0]
        sample_count = max(len(mfes), len(nets), len(rows))
        if sample_count <= 0:
            continue
        strategy_stats[strategy] = {
            "sample_count": sample_count,
            "avg_mfe_pct": mean(mfes) if mfes else 0.0,
            "avg_mae_pct": mean(maes) if maes else 0.0,
            "net_expectancy": mean(nets) if nets else 0.0,
            "win_rate": len(wins) / len(nets) if nets else 0.0,
            "mfe_1pct_hit_rate": sum(1 for v in mfes if v >= 0.010) / len(mfes) if mfes else 0.0,
            "mfe_0_8pct_hit_rate": sum(1 for v in mfes if v >= 0.008) / len(mfes) if mfes else 0.0,
            "mae_minus_0_8pct_hit_rate": sum(1 for v in maes if v <= -0.008) / len(maes) if maes else 0.0,
        }

    expected_by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in expected_edges:
        expected_by_strategy[_strategy_key(row)].append(row)
    expected_vs_actual: dict[str, dict[str, Any]] = {}
    for strategy, rows in expected_by_strategy.items():
        expected_net = [float(r.get("expected_net_edge_pct") or 0.0) for r in rows]
        expected_mfe = [float(r.get("expected_mfe_pct") or 0.0) for r in rows]
        expected_mae = [float(r.get("expected_mae_pct") or 0.0) for r in rows]
        actual = strategy_stats.get(strategy, {})
        actual_net = float(actual.get("net_expectancy") or 0.0)
        actual_mfe = float(actual.get("avg_mfe_pct") or 0.0)
        actual_mae = float(actual.get("avg_mae_pct") or 0.0)
        avg_expected_net = mean(expected_net) if expected_net else 0.0
        calibration_error = actual_net - avg_expected_net
        expected_vs_actual[strategy] = {
            "sample_count": len(rows),
            "expected_mfe_pct_avg": mean(expected_mfe) if expected_mfe else 0.0,
            "actual_mfe_pct_avg": actual_mfe,
            "expected_mae_pct_avg": mean(expected_mae) if expected_mae else 0.0,
            "actual_mae_pct_avg": actual_mae,
            "expected_net_edge_pct_avg": avg_expected_net,
            "actual_net_edge_pct_avg": actual_net,
            "calibration_error": calibration_error,
            "overestimated_count": sum(1 for v in expected_net if actual_net - v < -0.004),
            "underestimated_count": sum(1 for v in expected_net if actual_net - v > 0.004),
            "edge_quality_actual_expectancy": {
                quality: actual_net
                for quality in sorted({str(r.get("edge_quality") or "UNKNOWN") for r in rows})
            },
            "runner_allowed_count": sum(1 for r in rows if bool(r.get("runner_allowed"))),
        }

    cont_30s = [r for r in windows_30s if _strategy_key(r) == "momentum_continuation"]
    if cont_30s:
        stat = strategy_stats.setdefault("momentum_continuation", {"sample_count": 0})
        mfes_30 = [float(r.get("mfe_pct") or 0.0) for r in cont_30s]
        maes_30 = [float(r.get("mae_pct") or 0.0) for r in cont_30s]
        stat["mfe_0_3pct_60s_hit_rate"] = (
            sum(1 for v in mfes_30 if v >= 0.003) / len(mfes_30)
        )
        stat["fake_breakout_rate"] = (
            sum(1 for mfe, mae in zip(mfes_30, maes_30) if mfe < 0.003 and mae <= -0.004) / len(cont_30s)
        )

    top_reject_reasons = Counter(str(r.get("reject_reason") or "unknown") for r in rejects)
    stale_count = sum(
        1 for r in freshness
        if float(r.get("last_tick_age_sec") or 0.0) > 30.0
    )
    vwap_ready = sum(1 for r in freshness if bool(r.get("vwap_ready")))
    atr_ready = sum(1 for r in freshness if bool(r.get("atr_ready")))
    decisions = decide_promotions(strategy_stats)
    promotion_path = write_promotion_state(decisions, base_dir=promotion_dir, report_date=report_date)
    blocker_outcomes = build_missed_entry_counterfactual(
        report_date=report_date,
        shadow_dir=shadow_dir,
        output_dir=output_dir,
    )
    holding_exit_report = build_holding_exit_sentinel_report(
        report_date=report_date,
        diagnostics_dir=diagnostics_dir,
        output_dir=output_dir,
    )

    report = {
        "event_type": "daily_strategy_report",
        "generated_at": datetime.now().isoformat(),
        "date": day,
        "strategy_stats": strategy_stats,
        "promotion_decisions": [
            {
                "strategy": d.strategy,
                "state": d.state.value,
                "reason": d.reason,
                "sample_count": d.sample_count,
                "net_expectancy": d.net_expectancy,
                "win_rate": d.win_rate,
                "avg_mfe": d.avg_mfe,
                "avg_mae": d.avg_mae,
            }
            for d in decisions
        ],
        "conversion_funnel": route_summaries[-1] if route_summaries else {},
        "top_reject_reasons": dict(top_reject_reasons.most_common(20)),
        "blocker_outcomes": blocker_outcomes,
        "holding_exit_sentinel": holding_exit_report,
        "expected_vs_actual_edge": expected_vs_actual,
        "feature_freshness": {
            "sample_count": len(freshness),
            "stale_tick_ratio": stale_count / len(freshness) if freshness else 0.0,
            "vwap_ready_ratio": vwap_ready / len(freshness) if freshness else 0.0,
            "atr_ready_ratio": atr_ready / len(freshness) if freshness else 0.0,
        },
        "promotion_state_path": str(promotion_path),
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{day}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    diag_path = Path(diagnostics_dir) / f"{day}.jsonl"
    diag_path.parent.mkdir(parents=True, exist_ok=True)
    with diag_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False, default=str) + "\n")
    return report
