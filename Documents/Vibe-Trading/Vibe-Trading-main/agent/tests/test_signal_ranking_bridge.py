from __future__ import annotations

import json
from pathlib import Path

from src.trading.orchestrator_runner import apply_signal_ranking_selection


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_apply_signal_ranking_selection_from_json_scores(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config_path = run_dir / "config.json"
    _write_json(
        config_path,
        {
            "source": "auto",
            "interval": "5m",
            "codes": ["005930.KS", "000660.KS", "035420.KS"],
        },
    )
    _write_json(
        run_dir / "artifacts" / "symbol_scores.json",
        {
            "scores": {"005930.KS": 0.91, "000660.KS": 0.88, "035420.KS": 0.64},
            "ranked_symbols": ["005930.KS", "000660.KS", "035420.KS"],
        },
    )

    result = apply_signal_ranking_selection(
        "config.json",
        run_dir=str(run_dir),
        ranking_path="artifacts/symbol_scores.json",
        max_positions=2,
    )
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["005930.KS", "000660.KS"]
    assert saved["selected_symbols"] == ["005930.KS", "000660.KS"]
    assert result["scores_count"] == 3


def test_apply_signal_ranking_selection_from_snapshot_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config_path = run_dir / "config.json"
    _write_json(
        config_path,
        {
            "source": "auto",
            "interval": "15m",
            "codes": ["005930.KS", "000660.KS"],
        },
    )
    _write_json(
        run_dir / "artifacts" / "snapshots.json",
        {
            "snapshots": [
                {"timestamp": "2026-04-26T09:05:00", "symbol_scores": {"005930.KS": 0.5, "000660.KS": 0.3}},
                {"timestamp": "2026-04-26T09:10:00", "symbol_scores": {"005930.KS": 0.2, "000660.KS": 0.8}},
            ]
        },
    )

    result = apply_signal_ranking_selection(
        "config.json",
        run_dir=str(run_dir),
        ranking_path="artifacts/snapshots.json",
        as_of="2026-04-26T09:10:00",
        max_positions=1,
    )

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["000660.KS"]


def test_apply_signal_ranking_selection_from_csv(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config_path = run_dir / "config.json"
    _write_json(
        config_path,
        {
            "source": "auto",
            "interval": "5m",
            "codes": ["005930.KS", "000660.KS", "035420.KS"],
        },
    )
    ranking_path = run_dir / "artifacts" / "symbol_scores.csv"
    ranking_path.parent.mkdir(parents=True, exist_ok=True)
    ranking_path.write_text(
        "timestamp,symbol,score,rank\n"
        "2026-04-26T09:10:00,035420.KS,0.65,3\n"
        "2026-04-26T09:10:00,000660.KS,0.88,2\n"
        "2026-04-26T09:10:00,005930.KS,0.91,1\n",
        encoding="utf-8",
    )

    result = apply_signal_ranking_selection(
        "config.json",
        run_dir=str(run_dir),
        ranking_path="artifacts/symbol_scores.csv",
        as_of="2026-04-26T09:10:00",
        max_positions=2,
    )

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["005930.KS", "000660.KS"]


def test_apply_signal_ranking_selection_errors_on_missing_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config_path = run_dir / "config.json"
    _write_json(config_path, {"source": "auto", "interval": "1D", "codes": ["005930.KS"]})

    result = apply_signal_ranking_selection(
        "config.json",
        run_dir=str(run_dir),
        ranking_path="artifacts/missing.json",
    )

    assert result["status"] == "error"
