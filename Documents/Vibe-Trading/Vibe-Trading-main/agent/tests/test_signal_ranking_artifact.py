from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.trading.signal_ranking_artifact import (
    RUN_DIR_ENV,
    export_latest_signal_scores,
    extract_latest_signal_scores,
    write_symbol_scores_artifact,
)


def test_extract_latest_signal_scores_sorts_descending() -> None:
    index = pd.to_datetime(["2026-04-25 09:05:00", "2026-04-25 09:10:00"])
    signal_map = {
        "005930.KS": pd.Series([0.1, 0.7], index=index),
        "000660.KS": pd.Series([0.2, 0.4], index=index),
        "035420.KS": pd.Series([0.0, -0.1], index=index),
    }

    scores, ranked, timestamp = extract_latest_signal_scores(signal_map)

    assert scores["005930.KS"] == 0.7
    assert ranked == ["005930.KS", "000660.KS", "035420.KS"]
    assert timestamp.startswith("2026-04-25T09:10:00")


def test_write_symbol_scores_artifact_writes_json(tmp_path: Path) -> None:
    target = write_symbol_scores_artifact(
        {"005930.KS": 0.9, "000660.KS": 0.8},
        ranked_symbols=["005930.KS", "000660.KS"],
        run_dir=tmp_path,
        timestamp="2026-04-26T09:10:00",
        metadata={"selection_reason": "unit test"},
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ranked_symbols"] == ["005930.KS", "000660.KS"]
    assert payload["symbol_scores"]["005930.KS"] == 0.9
    assert payload["metadata"]["selection_reason"] == "unit test"


def test_export_latest_signal_scores_uses_env_run_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUN_DIR_ENV, str(tmp_path))
    index = pd.to_datetime(["2026-04-25 09:05:00", "2026-04-25 09:10:00"])
    signal_map = {
        "005930.KS": pd.Series([0.2, 0.6], index=index),
        "000660.KS": pd.Series([0.3, 0.5], index=index),
    }

    target = export_latest_signal_scores(
        signal_map,
        metadata={"selection_reason": "latest cross-sectional signal rank"},
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert target == tmp_path / "artifacts" / "symbol_scores.json"
    assert payload["ranked_symbols"] == ["005930.KS", "000660.KS"]
    assert payload["metadata"]["selection_reason"] == "latest cross-sectional signal rank"
