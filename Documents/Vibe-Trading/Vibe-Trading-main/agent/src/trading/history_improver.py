"""Helpers for improving a strategy from execution history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tools.path_utils import safe_path, safe_user_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_input_path(path: str, *, run_dir: str | None = None) -> Path:
    if run_dir and not Path(path).is_absolute():
        return safe_path(path, Path(run_dir))
    return safe_user_path(path)


def _load_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_history_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("trades", "history", "rows", "executions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _session_bucket(row: dict[str, Any]) -> str:
    explicit = str(row.get("session_bucket") or "").strip()
    if explicit:
        return explicit
    entry_time = str(row.get("entry_time") or row.get("datetime") or "")
    if "T09:" in entry_time or " 09:" in entry_time:
        return "opening"
    if "T10:" in entry_time or " 10:" in entry_time:
        return "morning"
    if "T13:" in entry_time or " 13:" in entry_time:
        return "afternoon"
    return "unknown"


def _extract_candidate_outcome(candidate: dict[str, Any]) -> float | None:
    for key in ("realized_pnl", "forward_return", "future_return", "outcome"):
        value = candidate.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _analyze_selection_misses(history_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    evaluated = 0
    misses = 0
    miss_examples: list[dict[str, Any]] = []

    for row in history_rows:
        snapshot = row.get("entry_signal_snapshot")
        if not isinstance(snapshot, dict):
            continue
        ranked_candidates = snapshot.get("ranked_candidates")
        if not isinstance(ranked_candidates, list):
            continue

        selected_outcomes = []
        rejected_outcomes = []
        for item in ranked_candidates:
            if not isinstance(item, dict):
                continue
            outcome = _extract_candidate_outcome(item)
            if outcome is None:
                continue
            symbol = str(item.get("symbol") or "")
            enriched = {
                "symbol": symbol,
                "rank": _to_int(item.get("rank"), 0),
                "score": _to_float(item.get("score")),
                "outcome": outcome,
            }
            if bool(item.get("selected")):
                selected_outcomes.append(enriched)
            else:
                rejected_outcomes.append(enriched)

        if not selected_outcomes or not rejected_outcomes:
            continue

        evaluated += 1
        best_rejected = max(rejected_outcomes, key=lambda item: item["outcome"])
        best_selected = max(selected_outcomes, key=lambda item: item["outcome"])
        if best_rejected["outcome"] > best_selected["outcome"]:
            misses += 1
            if len(miss_examples) < 3:
                miss_examples.append({
                    "selected_symbol": best_selected["symbol"],
                    "selected_outcome": round(best_selected["outcome"], 6),
                    "better_rejected_symbol": best_rejected["symbol"],
                    "better_rejected_outcome": round(best_rejected["outcome"], 6),
                })

    if not evaluated:
        return None

    miss_rate = misses / evaluated
    severity = "high" if miss_rate >= 0.5 else "medium" if miss_rate >= 0.3 else "low"
    return {
        "issue": "selection_miss_rate",
        "severity": severity,
        "miss_rate": round(miss_rate, 4),
        "evaluated_entries": evaluated,
        "miss_examples": miss_examples,
        "evidence": f"better rejected symbols beat selected symbols in {misses}/{evaluated} evaluated entries",
        "suggested_actions": [
            "review ranking threshold",
            "test top_n reduction",
            "re-weight selection score inputs",
        ],
    }


def build_diagnostic_report(
    history_rows: list[dict[str, Any]],
    *,
    strategy_id: str = "",
    strategy_version: str = "",
) -> dict[str, Any]:
    total = len(history_rows)
    realized = [row for row in history_rows if row.get("pnl") not in (None, "")]
    pnl_values = [_to_float(row.get("pnl")) for row in realized]
    winners = [p for p in pnl_values if p > 0]
    losers = [p for p in pnl_values if p < 0]
    trade_count = len(realized)
    win_rate = (len(winners) / trade_count) if trade_count else 0.0
    avg_win = (sum(winners) / len(winners)) if winners else 0.0
    avg_loss = (sum(losers) / len(losers)) if losers else 0.0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss else (0.0 if avg_win == 0 else 999.0)

    hold_minutes = []
    for row in history_rows:
        if row.get("hold_minutes") not in (None, ""):
            hold_minutes.append(_to_float(row.get("hold_minutes")))
        elif row.get("hold_days") not in (None, ""):
            hold_minutes.append(_to_float(row.get("hold_days")) * 1440.0)
    avg_hold_minutes = (sum(hold_minutes) / len(hold_minutes)) if hold_minutes else 0.0

    exit_reasons: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    session_counts: dict[str, int] = {}
    session_pnl: dict[str, float] = {}
    for row in history_rows:
        reason = str(row.get("exit_reason") or "unknown").strip() or "unknown"
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        symbol = str(row.get("symbol") or "unknown").strip() or "unknown"
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        bucket = _session_bucket(row)
        session_counts[bucket] = session_counts.get(bucket, 0) + 1
        session_pnl[bucket] = session_pnl.get(bucket, 0.0) + _to_float(row.get("pnl"))

    issues: list[dict[str, Any]] = []
    if trade_count and win_rate < 0.45 and profit_loss_ratio < 1.0:
        issues.append({
            "issue": "weak_trade_quality",
            "severity": "high",
            "evidence": f"win_rate={win_rate:.2%}, profit_loss_ratio={profit_loss_ratio:.2f}",
            "suggested_actions": ["tighten entry filters", "reduce low-conviction symbols", "review session bucket losses"],
        })
    if total and exit_reasons.get("time_stop", 0) / max(total, 1) > 0.4:
        issues.append({
            "issue": "over_reliance_on_time_stop",
            "severity": "medium",
            "evidence": f"time_stop exits={exit_reasons.get('time_stop', 0)}/{total}",
            "suggested_actions": ["tighten signal_exit", "move time_stop earlier", "reduce weak opening entries"],
        })
    if symbol_counts:
        top_symbol, top_count = max(symbol_counts.items(), key=lambda item: item[1])
        if top_count / max(total, 1) > 0.35:
            issues.append({
                "issue": "symbol_concentration",
                "severity": "medium",
                "evidence": f"{top_symbol} accounts for {top_count}/{total} trades",
                "suggested_actions": ["cap per-symbol frequency", "exclude weak symbols", "rebalance top_n"],
            })
    if session_pnl:
        worst_bucket, worst_pnl = min(session_pnl.items(), key=lambda item: item[1])
        if worst_pnl < 0:
            issues.append({
                "issue": "weak_session_bucket",
                "severity": "medium",
                "evidence": f"{worst_bucket} session cumulative pnl={worst_pnl:.2f}",
                "suggested_actions": [f"de-emphasize {worst_bucket}", "tighten bucket-specific filters"],
            })
    selection_miss_issue = _analyze_selection_misses(history_rows)
    if selection_miss_issue:
        issues.append(selection_miss_issue)

    recommended_focus = [issue["issue"] for issue in issues[:3]]
    return {
        "generated_at": _now_iso(),
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "history_summary": {
            "records_total": total,
            "realized_trade_count": trade_count,
            "win_rate": round(win_rate, 4),
            "profit_loss_ratio": round(profit_loss_ratio, 3),
            "avg_hold_minutes": round(avg_hold_minutes, 1),
            "exit_reason_distribution": exit_reasons,
            "session_distribution": session_counts,
            "session_pnl": {k: round(v, 2) for k, v in session_pnl.items()},
            "top_symbols": sorted(symbol_counts.items(), key=lambda item: item[1], reverse=True)[:5],
        },
        "issues": issues,
        "recommended_focus": recommended_focus,
    }


def build_improvement_candidates(
    diagnostic_report: dict[str, Any],
    *,
    max_candidates: int = 5,
) -> dict[str, Any]:
    issues = list(diagnostic_report.get("issues") or [])
    candidates: list[dict[str, Any]] = []

    for issue in issues:
        kind = issue.get("issue")
        if kind == "over_reliance_on_time_stop":
            candidates.append({
                "candidate_id": "tighten-time-stop",
                "title": "Tighten time stop",
                "change_type": "exit_policy",
                "proposed_change": {"time_stop": "10:30 force exit"},
                "rationale": issue.get("evidence", ""),
                "expected_effect": "reduce late low-conviction exits",
            })
        elif kind == "symbol_concentration":
            candidates.append({
                "candidate_id": "reduce-top-n",
                "title": "Reduce concurrent symbols",
                "change_type": "positioning",
                "proposed_change": {"top_n": 2},
                "rationale": issue.get("evidence", ""),
                "expected_effect": "reduce symbol concentration and improve selectivity",
            })
        elif kind == "weak_session_bucket":
            evidence = str(issue.get("evidence") or "")
            weak_bucket = evidence.split(" ", 1)[0] if evidence else "unknown"
            candidates.append({
                "candidate_id": f"deemphasize-{weak_bucket}",
                "title": "De-emphasize weak session bucket",
                "change_type": "filter",
                "proposed_change": {"exclude_session_bucket": weak_bucket},
                "rationale": evidence,
                "expected_effect": "avoid systematically weak time windows",
            })
        elif kind == "weak_trade_quality":
            candidates.append({
                "candidate_id": "raise-entry-threshold",
                "title": "Raise entry threshold",
                "change_type": "filter",
                "proposed_change": {"volume_filter_multiplier": 1.5},
                "rationale": issue.get("evidence", ""),
                "expected_effect": "filter out low-conviction entries",
            })
        elif kind == "selection_miss_rate":
            candidates.append({
                "candidate_id": "tighten-selection-threshold",
                "title": "Tighten selection threshold",
                "change_type": "selection",
                "proposed_change": {"selection_score_threshold": 0.1},
                "rationale": issue.get("evidence", ""),
                "expected_effect": "reduce cases where rejected symbols outperform selected ones",
            })
            candidates.append({
                "candidate_id": "reweight-ranking-inputs",
                "title": "Re-weight ranking inputs",
                "change_type": "selection",
                "proposed_change": {"ranking_weight_review": True},
                "rationale": issue.get("evidence", ""),
                "expected_effect": "improve symbol ranking quality before top_n selection",
            })

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        cid = str(candidate.get("candidate_id") or "")
        if cid and cid not in seen:
            deduped.append(candidate)
            seen.add(cid)

    return {
        "generated_at": _now_iso(),
        "strategy_id": diagnostic_report.get("strategy_id", ""),
        "strategy_version": diagnostic_report.get("strategy_version", ""),
        "based_on_issues": [issue.get("issue") for issue in issues],
        "candidates": deduped[:max(1, max_candidates)],
    }


def build_promotion_decision(
    comparison_payload: dict[str, Any],
    *,
    min_return_delta: float = 0.0,
    max_drawdown_regression: float = 0.0,
    min_trade_count: int = 20,
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = comparison_payload.get("baseline") or {}
    candidates = list(comparison_payload.get("candidates") or [])

    normalized_candidates: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []
    base_return = _to_float(baseline.get("total_return"))
    base_mdd = abs(_to_float(baseline.get("max_drawdown")))

    for candidate in candidates:
        metrics = candidate.get("metrics") or {}
        total_return = _to_float(metrics.get("total_return"))
        max_drawdown = abs(_to_float(metrics.get("max_drawdown")))
        trade_count = _to_int(metrics.get("trade_count"))
        return_delta = total_return - base_return
        drawdown_delta = max_drawdown - base_mdd
        status = "REJECT"
        reasons: list[str] = []
        if trade_count < min_trade_count:
            reasons.append("insufficient_trade_count")
        if return_delta < min_return_delta:
            reasons.append("return_not_improved")
        if drawdown_delta > max_drawdown_regression:
            reasons.append("drawdown_regression")
        if not reasons:
            status = "APPROVE"
        normalized = {
            "candidate_id": candidate.get("candidate_id", ""),
            "title": candidate.get("title", ""),
            "metrics": metrics,
            "return_delta": round(return_delta, 6),
            "drawdown_delta": round(drawdown_delta, 6),
            "status": status,
            "reasons": reasons,
        }
        normalized_candidates.append(normalized)
        if status == "APPROVE":
            approved.append(normalized)

    approved.sort(key=lambda item: item["return_delta"], reverse=True)
    best = approved[0] if approved else None
    promotion_decision = {
        "generated_at": _now_iso(),
        "status": "APPROVED" if best else "REJECTED",
        "selected_candidate_id": best.get("candidate_id", "") if best else "",
        "selected_title": best.get("title", "") if best else "",
        "promotion_mode": "paper_first" if best else "hold_baseline",
        "blocking_reasons": [] if best else ["no_candidate_passed"],
        "baseline_strategy_id": comparison_payload.get("strategy_id", ""),
        "baseline_strategy_version": comparison_payload.get("strategy_version", ""),
    }
    comparison = {
        "generated_at": _now_iso(),
        "strategy_id": comparison_payload.get("strategy_id", ""),
        "strategy_version": comparison_payload.get("strategy_version", ""),
        "baseline": baseline,
        "candidates": normalized_candidates,
    }
    return comparison, promotion_decision


def write_history_improvement_artifacts(
    run_dir: Path,
    *,
    diagnostic_report: dict[str, Any] | None = None,
    improvement_candidates: dict[str, Any] | None = None,
    improvement_comparison: dict[str, Any] | None = None,
    promotion_decision: dict[str, Any] | None = None,
) -> dict[str, Path]:
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    payloads = {
        "diagnostic_report": diagnostic_report,
        "improvement_candidates": improvement_candidates,
        "improvement_comparison": improvement_comparison,
        "promotion_decision": promotion_decision,
    }
    for name, payload in payloads.items():
        if payload is None:
            continue
        path = artifacts_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs[name] = path
    return outputs
