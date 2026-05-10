"""Realtime broker quote -> symbol ranking -> selected_symbols bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.tools.path_utils import safe_path as _safe_path
from src.trading.orchestrator_runner import select_orchestrator_symbols
from src.trading.signal_ranking_artifact import write_symbol_scores_artifact


def _extract_message_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    rows.append(item)
        for value in payload.values():
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                rows.extend(value)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                rows.extend(_extract_message_rows(item) or [item])
    return rows


def extract_realtime_symbol_scores(
    messages: list[dict[str, Any]] | dict[str, Any],
    *,
    score_field: str = "flu_rt",
) -> tuple[dict[str, float], list[str]]:
    rows = _extract_message_rows(messages)
    scores: dict[str, float] = {}
    for row in rows:
        symbol = str(
            row.get("symbol")
            or row.get("stk_cd")
            or row.get("code")
            or row.get("item")
            or ""
        ).strip()
        if not symbol:
            continue
        raw_score = row.get(score_field)
        if raw_score in (None, "") and score_field != "score":
            raw_score = row.get("score")
        if raw_score in (None, "") and score_field != "cur_prc":
            raw_score = row.get("cur_prc")
        try:
            scores[symbol] = float(str(raw_score).replace(",", ""))
        except (TypeError, ValueError):
            continue
    ranked = sorted(scores, key=lambda code: (-scores[code], code))
    return scores, ranked


def apply_realtime_selection_update(
    path: str,
    *,
    run_dir: str,
    messages: list[dict[str, Any]] | dict[str, Any],
    score_field: str = "flu_rt",
    max_positions: int | None = None,
    selection_reason: str | None = None,
    artifact_name: str = "realtime_symbol_scores.json",
) -> dict[str, Any]:
    scores, ranked = extract_realtime_symbol_scores(messages, score_field=score_field)
    if not scores:
        return {"status": "error", "error": "no realtime symbol scores extracted"}

    artifact = write_symbol_scores_artifact(
        scores,
        ranked_symbols=ranked,
        run_dir=run_dir,
        artifact_name=artifact_name,
        metadata={
            "source": "broker_realtime",
            "score_field": score_field,
            "selection_reason": selection_reason or "broker realtime quote update",
        },
    )
    result = select_orchestrator_symbols(
        path,
        run_dir=run_dir,
        candidate_symbols=ranked,
        symbol_scores=scores,
        max_positions=max_positions,
        selection_reason=selection_reason or "broker realtime quote update",
    )
    if result.get("status") != "ok":
        return result
    result["ranking_artifact"] = str(artifact)
    result["scores"] = scores
    return result


def update_realtime_selection_from_file(
    path: str,
    *,
    run_dir: str,
    message_path: str,
    score_field: str = "flu_rt",
    max_positions: int | None = None,
    selection_reason: str | None = None,
) -> dict[str, Any]:
    resolved = _safe_path(message_path, Path(run_dir))
    if not resolved.exists():
        return {"status": "error", "error": f"message file not found: {message_path}"}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"invalid realtime message json: {exc}"}
    result = apply_realtime_selection_update(
        path,
        run_dir=run_dir,
        messages=payload,
        score_field=score_field,
        max_positions=max_positions,
        selection_reason=selection_reason or f"broker realtime file: {resolved.name}",
    )
    if result.get("status") == "ok":
        result["message_path"] = str(resolved)
    return result
