"""Helpers for orchestrator-managed strategy configs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.tools.ensure_exit_policy_tool import DEFAULT_EXIT_POLICY
from src.tools.path_utils import safe_path as _safe_path
from src.trading.paper_state import extract_exit_policy, requires_explicit_exit_guard


def _normalize_symbol_scores(raw_scores: dict[str, Any] | None) -> dict[str, float]:
    scores: dict[str, float] = {}
    for key, value in (raw_scores or {}).items():
        try:
            scores[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return scores


def _pick_snapshot(payload: list[dict[str, Any]], as_of: str | None) -> dict[str, Any] | None:
    if not payload:
        return None
    if not as_of:
        return payload[-1]
    for item in reversed(payload):
        if str(item.get("timestamp") or "") == as_of:
            return item
    return payload[-1]


def _load_ranking_scores(ranking_path: Path, *, as_of: str | None = None) -> tuple[dict[str, float], list[str]]:
    suffix = ranking_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(ranking_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if isinstance(payload.get("symbol_scores"), dict):
                return _normalize_symbol_scores(payload.get("symbol_scores")), list(payload.get("ranked_symbols") or [])
            if isinstance(payload.get("scores"), dict):
                return _normalize_symbol_scores(payload.get("scores")), list(payload.get("ranked_symbols") or [])
            snapshots = payload.get("snapshots")
            if isinstance(snapshots, list):
                snapshot = _pick_snapshot([item for item in snapshots if isinstance(item, dict)], as_of)
                if snapshot:
                    if isinstance(snapshot.get("symbol_scores"), dict):
                        return _normalize_symbol_scores(snapshot.get("symbol_scores")), list(snapshot.get("ranked_symbols") or [])
                    if isinstance(snapshot.get("scores"), dict):
                        return _normalize_symbol_scores(snapshot.get("scores")), list(snapshot.get("ranked_symbols") or [])
        if isinstance(payload, list):
            rows = [item for item in payload if isinstance(item, dict)]
            snapshot = _pick_snapshot(rows, as_of)
            if snapshot:
                if isinstance(snapshot.get("symbol_scores"), dict):
                    return _normalize_symbol_scores(snapshot.get("symbol_scores")), list(snapshot.get("ranked_symbols") or [])
                if isinstance(snapshot.get("scores"), dict):
                    return _normalize_symbol_scores(snapshot.get("scores")), list(snapshot.get("ranked_symbols") or [])
                symbol = snapshot.get("symbol") or snapshot.get("code") or snapshot.get("ticker")
                score = snapshot.get("score")
                if symbol is not None and score is not None:
                    ordered_scores = _normalize_symbol_scores({str(row.get("symbol") or row.get("code") or row.get("ticker")): row.get("score") for row in rows})
                    ranked = [str(row.get("symbol") or row.get("code") or row.get("ticker")) for row in rows if row.get("symbol") or row.get("code") or row.get("ticker")]
                    return ordered_scores, ranked
        raise ValueError(f"unsupported ranking JSON format: {ranking_path.name}")

    if suffix == ".csv":
        with ranking_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return {}, []
        target_rows = rows
        if as_of:
            exact = [row for row in rows if str(row.get("timestamp") or "") == as_of]
            if exact:
                target_rows = exact
        scores: dict[str, float] = {}
        ranked: list[str] = []
        for row in target_rows:
            symbol = row.get("symbol") or row.get("code") or row.get("ticker")
            score = row.get("score")
            if not symbol or score in (None, ""):
                continue
            try:
                score_value = float(score)
            except (TypeError, ValueError):
                continue
            symbol_key = str(symbol)
            if symbol_key not in scores:
                ranked.append(symbol_key)
            scores[symbol_key] = score_value
        if "rank" in rows[0]:
            ranked.sort(key=lambda code: next((int(float(row["rank"])) for row in target_rows if (row.get("symbol") or row.get("code") or row.get("ticker")) == code and row.get("rank") not in (None, "")), 10**9))
        return scores, ranked

    raise ValueError(f"unsupported ranking artifact type: {ranking_path.suffix or 'unknown'}")


def select_orchestrator_symbols(
    path: str,
    *,
    run_dir: str,
    candidate_symbols: list[str] | None = None,
    symbol_scores: dict[str, float] | None = None,
    max_positions: int | None = None,
    exclude_symbols: list[str] | None = None,
    selection_reason: str | None = None,
) -> dict[str, Any]:
    resolved = _safe_path(path, Path(run_dir))
    if not resolved.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    try:
        config = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"config.json parse error: {exc}"}

    if not isinstance(config, dict):
        return {"status": "error", "error": "config must be a JSON object"}

    config_codes = config.get("codes")
    universe = [str(code) for code in config_codes] if isinstance(config_codes, list) else []
    requested = [str(code) for code in (candidate_symbols or universe)]
    if not requested:
        return {"status": "error", "error": "no candidate symbols available"}

    exclude = {str(code) for code in (exclude_symbols or [])}
    universe_set = set(universe)

    filtered: list[str] = []
    for code in requested:
        if code in exclude:
            continue
        if universe and code not in universe_set:
            continue
        if code not in filtered:
            filtered.append(code)

    if not filtered:
        return {"status": "error", "error": "no symbols remained after filtering"}

    raw_limit = max_positions
    if raw_limit is None:
        raw_limit = config.get("max_positions")
    if raw_limit is None:
        raw_limit = config.get("max_holdings")
    if raw_limit is None:
        raw_limit = len(filtered)

    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return {"status": "error", "error": f"invalid max_positions: {raw_limit}"}

    if limit <= 0:
        return {"status": "error", "error": "max_positions must be >= 1"}

    index_map = {code: idx for idx, code in enumerate(filtered)}
    scores = {str(k): float(v) for k, v in (symbol_scores or {}).items()}
    ranked = sorted(
        filtered,
        key=lambda code: (-scores.get(code, 0.0), index_map[code]),
    )
    selected = ranked[:limit]

    config["selected_symbols"] = selected
    config["symbol_selection"] = {
        "candidate_symbols": filtered,
        "ranked_symbols": ranked,
        "selected_symbols": selected,
        "max_positions": limit,
        "selection_reason": str(selection_reason or ""),
        "scores": {code: scores[code] for code in ranked if code in scores},
    }

    resolved.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "path": str(resolved),
        "selected_symbols": selected,
        "ranked_symbols": ranked,
        "max_positions": limit,
        "selection_reason": config["symbol_selection"]["selection_reason"],
    }


def apply_signal_ranking_selection(
    path: str,
    *,
    run_dir: str,
    ranking_path: str,
    as_of: str | None = None,
    max_positions: int | None = None,
    exclude_symbols: list[str] | None = None,
    selection_reason: str | None = None,
) -> dict[str, Any]:
    base_dir = Path(run_dir)
    resolved_ranking = _safe_path(ranking_path, base_dir)
    if not resolved_ranking.exists():
        return {"status": "error", "error": f"Ranking artifact not found: {ranking_path}"}

    try:
        symbol_scores, ranked_symbols = _load_ranking_scores(resolved_ranking, as_of=as_of)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"status": "error", "error": str(exc)}

    result = select_orchestrator_symbols(
        path,
        run_dir=run_dir,
        candidate_symbols=ranked_symbols or list(symbol_scores.keys()),
        symbol_scores=symbol_scores,
        max_positions=max_positions,
        exclude_symbols=exclude_symbols,
        selection_reason=selection_reason or f"ranking artifact: {resolved_ranking.name}",
    )
    if result.get("status") != "ok":
        return result

    result["ranking_path"] = str(resolved_ranking)
    result["scores_count"] = len(symbol_scores)
    result["as_of"] = as_of or ""
    return result


def prepare_orchestrator_config(
    path: str,
    *,
    run_dir: str,
    mode: str = "research",
    selected_symbols: list[str] | None = None,
    strategy_id: str | None = None,
    strategy_version: str | None = None,
    signal_exit: str | None = None,
    stop_loss: str | None = None,
    take_profit: str | None = None,
    time_stop: str | None = None,
    fallback_rule: str | None = None,
) -> dict[str, Any]:
    resolved = _safe_path(path, Path(run_dir))
    if not resolved.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    try:
        config = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"config.json parse error: {exc}"}

    if not isinstance(config, dict):
        return {"status": "error", "error": "config must be a JSON object"}

    normalized_mode = str(mode or config.get("mode") or "research").strip().lower()
    if normalized_mode not in {"research", "paper", "live"}:
        return {"status": "error", "error": f"unsupported mode: {normalized_mode}"}

    config["mode"] = normalized_mode
    config["selected_symbols"] = list(selected_symbols or config.get("selected_symbols") or [])
    if strategy_id:
        config["strategy_id"] = str(strategy_id)
    if strategy_version:
        config["strategy_version"] = str(strategy_version)

    overrides = {
        "signal_exit": signal_exit,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "time_stop": time_stop,
        "fallback_rule": fallback_rule,
    }
    current = extract_exit_policy(config)
    merged = dict(DEFAULT_EXIT_POLICY)
    merged.update({k: v for k, v in overrides.items() if v})
    merged.update({k: v for k, v in current.items() if v})

    if requires_explicit_exit_guard(config):
        existing = config.get("exit_policy")
        if not isinstance(existing, dict):
            existing = {}
        config["exit_policy"] = {**existing, **merged}

    resolved.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "path": str(resolved),
        "mode": normalized_mode,
        "selected_symbols": config["selected_symbols"],
        "exit_policy": config.get("exit_policy", {}),
        "strategy_id": config.get("strategy_id", ""),
        "strategy_version": config.get("strategy_version", ""),
    }
