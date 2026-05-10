"""Helpers for paper/live decision artifacts and intraday exit guards."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


INTRADAY_INTERVALS = {"1m", "5m", "15m", "30m", "1H"}
TRADE_DECISIONS = ("BUY", "SELL", "REDUCE", "HOLD")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_intraday_config(config: dict[str, Any]) -> bool:
    return str(config.get("interval", "1D")).strip() in INTRADAY_INTERVALS


def is_kr_config(config: dict[str, Any]) -> bool:
    codes = [str(c).upper() for c in (config.get("codes") or [])]
    return any(code.endswith((".KS", ".KQ")) for code in codes)


def requires_explicit_exit_guard(config: dict[str, Any]) -> bool:
    mode = str(config.get("mode", "research")).strip().lower()
    return mode in {"paper", "live"} and is_kr_config(config) and is_intraday_config(config)


def extract_exit_policy(config: dict[str, Any]) -> dict[str, str]:
    policy = config.get("exit_policy") or {}
    out = {
        "signal_exit": str(policy.get("signal_exit") or config.get("signal_exit") or "").strip(),
        "stop_loss": str(policy.get("stop_loss") or config.get("stop_loss") or "").strip(),
        "take_profit": str(policy.get("take_profit") or config.get("take_profit") or "").strip(),
        "time_stop": str(policy.get("time_stop") or config.get("time_stop") or "").strip(),
        "fallback_rule": str(policy.get("fallback_rule") or config.get("fallback_rule") or "").strip(),
    }
    return out


def validate_exit_policy(config: dict[str, Any]) -> str | None:
    if not requires_explicit_exit_guard(config):
        return None

    policy = extract_exit_policy(config)
    if not policy["stop_loss"]:
        return "KR intraday paper/live strategies require stop_loss in config.exit_policy or top-level config"
    if not policy["take_profit"]:
        return "KR intraday paper/live strategies require take_profit in config.exit_policy or top-level config"
    if not policy["time_stop"]:
        return "KR intraday paper/live strategies require time_stop in config.exit_policy or top-level config"
    if not policy["fallback_rule"]:
        return "KR intraday paper/live strategies require fallback_rule in config.exit_policy or top-level config"
    return None


def _read_metrics(metrics_path: Path) -> dict[str, Any]:
    if not metrics_path.exists():
        return {}
    try:
        with metrics_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[0]
    parsed: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or value == "":
            parsed[key] = value
            continue
        try:
            parsed[key] = int(value) if value.isdigit() else float(value)
        except Exception:
            parsed[key] = value
    return parsed


def _extract_symbol_scores(config: dict[str, Any]) -> dict[str, float]:
    raw = {}
    symbol_selection = config.get("symbol_selection")
    if isinstance(symbol_selection, dict) and isinstance(symbol_selection.get("scores"), dict):
        raw = symbol_selection.get("scores") or {}
    elif isinstance(config.get("symbol_scores"), dict):
        raw = config.get("symbol_scores") or {}

    scores: dict[str, float] = {}
    for key, value in raw.items():
        try:
            scores[str(key)] = float(value)
        except Exception:
            continue
    return scores


def _extract_entry_signal_snapshot(config: dict[str, Any], symbol_scores: dict[str, float]) -> dict[str, Any]:
    snapshot = config.get("entry_signal_snapshot")
    if isinstance(snapshot, dict):
        return snapshot

    selected_symbols = list(config.get("selected_symbols") or [])
    symbol_selection = config.get("symbol_selection") if isinstance(config.get("symbol_selection"), dict) else {}
    ranked_symbols = list(symbol_selection.get("ranked_symbols") or [])
    candidate_symbols = list(symbol_selection.get("candidate_symbols") or ranked_symbols or list(symbol_scores.keys()))
    if not ranked_symbols:
        ranked_symbols = sorted(candidate_symbols, key=lambda symbol: (-symbol_scores.get(symbol, 0.0), symbol))
    ranked_candidates = [
        {
            "symbol": symbol,
            "score": symbol_scores.get(symbol),
            "selected": symbol in selected_symbols,
            "rank": idx + 1,
        }
        for idx, symbol in enumerate(ranked_symbols)
    ]
    rejected_symbols = [symbol for symbol in ranked_symbols if symbol not in selected_symbols]
    return {
        "candidate_symbols": candidate_symbols,
        "ranked_symbols": ranked_symbols,
        "selected_symbols": selected_symbols,
        "symbol_scores": {symbol: symbol_scores[symbol] for symbol in selected_symbols if symbol in symbol_scores},
        "ranked_candidates": ranked_candidates,
        "rejected_symbols": rejected_symbols,
        "top_ranked_not_selected": rejected_symbols[:5],
        "selection_reason": str((config.get("symbol_selection") or {}).get("selection_reason") or ""),
    }


def _build_risk_report(config: dict[str, Any], metrics: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    trade_count = int(float(metrics.get("trade_count", 0) or 0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0) or 0.0)
    max_drawdown_limit = float(config.get("max_drawdown_limit", 0.2))
    min_trade_count = int(config.get("min_trade_count", 20 if is_intraday_config(config) else 1))

    checks = [
        {
            "name": "trade_count",
            "status": "PASS" if trade_count >= min_trade_count else "FAIL",
            "threshold": min_trade_count,
            "observed": trade_count,
            "message": "sufficient trades" if trade_count >= min_trade_count else "too few trades",
        },
        {
            "name": "max_drawdown",
            "status": "PASS" if abs(max_drawdown) <= max_drawdown_limit else "FAIL",
            "threshold": max_drawdown_limit,
            "observed": max_drawdown,
            "message": "drawdown within limit" if abs(max_drawdown) <= max_drawdown_limit else "drawdown above limit",
        },
    ]
    blocking = [c["name"] for c in checks if c["status"] == "FAIL"]
    return {
        "status": "PASS" if not blocking else "FAIL",
        "generated_at": generated_at,
        "checks": checks,
        "recent_window_summary": {},
        "blocking_reasons": blocking,
    }


def _build_trade_decision(
    config: dict[str, Any],
    risk_report: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    selected_symbols = list(config.get("selected_symbols") or [])
    symbol_scores = _extract_symbol_scores(config)
    entry_signal_snapshot = _extract_entry_signal_snapshot(config, symbol_scores)
    decision = "HOLD"
    blocked_by = list(risk_report.get("blocking_reasons") or [])
    if risk_report.get("status") == "PASS" and selected_symbols:
        decision = "BUY"

    if decision not in TRADE_DECISIONS:
        decision = "HOLD"

    return {
        "decision": decision,
        "mode": str(config.get("mode", "research")).strip().lower(),
        "market": "kr" if is_kr_config(config) else "kr",
        "generated_at": generated_at,
        "strategy_id": str(config.get("strategy_id") or Path(str(config.get("_run_dir", ""))).name or "unknown"),
        "strategy_version": str(config.get("strategy_version") or ""),
        "decision_reason": "risk gate blocked trading" if blocked_by else "paper/live candidate ready",
        "universe": list(config.get("codes") or []),
        "selected_symbols": selected_symbols,
        "symbol_scores": symbol_scores,
        "symbol_selection": config.get("symbol_selection") if isinstance(config.get("symbol_selection"), dict) else {},
        "entry_signal_snapshot": entry_signal_snapshot,
        "blocked_by": blocked_by,
        "exit_policy": extract_exit_policy(config),
        "exit_policy_snapshot": extract_exit_policy(config),
        "confidence": 0.0 if blocked_by else 0.5,
    }


def _build_execution_plan(
    config: dict[str, Any],
    trade_decision: dict[str, Any],
    risk_report: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    mode = str(config.get("mode", "research")).strip().lower()
    ready = risk_report.get("status") == "PASS" and trade_decision.get("decision") != "HOLD"
    side = trade_decision.get("decision", "HOLD")
    if side == "HOLD":
        order_side = "NONE"
    else:
        order_side = side

    symbol_scores = _extract_symbol_scores(config)

    orders = [
        {
            "symbol": symbol,
            "side": order_side,
            "selection_score": symbol_scores.get(symbol),
            "qty_policy": str(config.get("qty_policy") or "equal_weight"),
            "limit_policy": str(config.get("limit_policy") or "marketable_limit"),
            "time_in_force": str(config.get("time_in_force") or "DAY"),
            "notes": "paper/live candidate generated by orchestrator artifacts",
        }
        for symbol in (trade_decision.get("selected_symbols") or [])
    ]
    return {
        "mode": mode,
        "generated_at": generated_at,
        "ready": ready,
        "approval_required": mode == "live",
        "broker": str(config.get("broker") or ""),
        "selected_symbols": list(trade_decision.get("selected_symbols") or []),
        "entry_signal_snapshot": trade_decision.get("entry_signal_snapshot") or {},
        "exit_policy_snapshot": trade_decision.get("exit_policy_snapshot") or {},
        "session_window": {
            "start": str(config.get("session_start") or "09:00"),
            "end": str(config.get("session_end") or ("15:20" if mode == "live" else "11:00")),
        },
        "orders": orders,
        "preflight_checks": [
            "risk_report.status == PASS",
            "trade_decision.decision != HOLD",
            "broker connected for live mode",
            "session is open",
        ],
    }


def _update_execution_history(
    run_dir: Path,
    config: dict[str, Any],
    trade_decision: dict[str, Any],
    risk_report: dict[str, Any],
    execution_plan: dict[str, Any],
    *,
    generated_at: str,
) -> Path:
    history_path = run_dir / "artifacts" / "execution_history.json"
    history: list[dict[str, Any]] = []
    if history_path.exists():
        try:
            existing = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                history = [row for row in existing if isinstance(row, dict)]
        except Exception:
            history = []

    record = {
        "generated_at": generated_at,
        "mode": str(config.get("mode", "research")).strip().lower(),
        "strategy_id": str(config.get("strategy_id") or Path(str(config.get("_run_dir", ""))).name or "unknown"),
        "strategy_version": str(config.get("strategy_version") or ""),
        "market": "kr" if is_kr_config(config) else "kr",
        "decision": trade_decision.get("decision", "HOLD"),
        "risk_status": risk_report.get("status", "FAIL"),
        "blocked_by": list(trade_decision.get("blocked_by") or []),
        "universe": list(config.get("codes") or []),
        "selected_symbols": list(trade_decision.get("selected_symbols") or []),
        "symbol_scores": trade_decision.get("symbol_scores") or {},
        "symbol_selection": trade_decision.get("symbol_selection") or {},
        "entry_signal_snapshot": trade_decision.get("entry_signal_snapshot") or {},
        "exit_policy_snapshot": trade_decision.get("exit_policy_snapshot") or {},
        "execution_plan_snapshot": execution_plan,
    }
    history.append(record)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history_path


def write_paper_mode_artifacts(run_dir: Path, config: dict[str, Any]) -> dict[str, Path]:
    generated_at = _now_iso()
    config = dict(config)
    config["_run_dir"] = str(run_dir)
    metrics = _read_metrics(run_dir / "artifacts" / "metrics.csv")
    risk_report = _build_risk_report(config, metrics, generated_at=generated_at)
    trade_decision = _build_trade_decision(config, risk_report, generated_at=generated_at)
    execution_plan = _build_execution_plan(config, trade_decision, risk_report, generated_at=generated_at)

    outputs = {
        "risk_report": run_dir / "artifacts" / "risk_report.json",
        "trade_decision": run_dir / "artifacts" / "trade_decision.json",
        "execution_plan": run_dir / "artifacts" / "execution_plan.json",
    }
    outputs["risk_report"].write_text(json.dumps(risk_report, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["trade_decision"].write_text(json.dumps(trade_decision, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["execution_plan"].write_text(json.dumps(execution_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["execution_history"] = _update_execution_history(
        run_dir,
        config,
        trade_decision,
        risk_report,
        execution_plan,
        generated_at=generated_at,
    )
    return outputs
