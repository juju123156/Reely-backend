"""Helpers for writing orchestrator-friendly signal ranking artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


RUN_DIR_ENV = "VIBE_TRADING_RUN_DIR"


def _resolve_run_dir(run_dir: str | Path | None = None) -> Path:
    candidate = run_dir or os.getenv(RUN_DIR_ENV, "")
    if not candidate:
        raise ValueError(f"run_dir is required or {RUN_DIR_ENV} must be set")
    return Path(candidate).expanduser().resolve()


def extract_latest_signal_scores(signal_map: dict[str, Any]) -> tuple[dict[str, float], list[str], str]:
    """Extract latest scalar scores from a code -> signal Series mapping."""
    scores: dict[str, float] = {}
    timestamp = ""
    for code, series in (signal_map or {}).items():
        if series is None:
            continue
        cleaned = series.dropna()
        if cleaned.empty:
            continue
        latest = cleaned.iloc[-1]
        try:
            scores[str(code)] = float(latest)
        except (TypeError, ValueError):
            continue
        if not timestamp:
            idx = cleaned.index[-1]
            timestamp = str(getattr(idx, "isoformat", lambda: idx)())

    ranked = sorted(scores, key=lambda code: (-scores[code], code))
    return scores, ranked, timestamp


def write_symbol_scores_artifact(
    symbol_scores: dict[str, Any],
    *,
    ranked_symbols: list[str] | None = None,
    run_dir: str | Path | None = None,
    timestamp: str | None = None,
    artifact_name: str = "symbol_scores.json",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a JSON ranking artifact under ``artifacts/``."""
    resolved_run_dir = _resolve_run_dir(run_dir)
    artifacts_dir = resolved_run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    normalized_scores: dict[str, float] = {}
    for key, value in (symbol_scores or {}).items():
        try:
            normalized_scores[str(key)] = float(value)
        except (TypeError, ValueError):
            continue

    ordered = list(ranked_symbols or [])
    if not ordered:
        ordered = sorted(normalized_scores, key=lambda code: (-normalized_scores[code], code))

    payload = {
        "symbol_scores": normalized_scores,
        "ranked_symbols": ordered,
        "timestamp": str(timestamp or ""),
        "metadata": metadata or {},
    }
    target = artifacts_dir / artifact_name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def export_latest_signal_scores(
    signal_map: dict[str, Any],
    *,
    run_dir: str | Path | None = None,
    artifact_name: str = "symbol_scores.json",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Derive last-step scores from ``signal_map`` and write them."""
    scores, ranked, timestamp = extract_latest_signal_scores(signal_map)
    return write_symbol_scores_artifact(
        scores,
        ranked_symbols=ranked,
        run_dir=run_dir,
        timestamp=timestamp,
        artifact_name=artifact_name,
        metadata=metadata,
    )
