from __future__ import annotations

import json
from pathlib import Path

from src.trading.orchestrator_runner import select_orchestrator_symbols


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_select_orchestrator_symbols_uses_scores_and_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "source": "auto",
            "interval": "5m",
            "codes": ["005930.KS", "000660.KS", "035420.KS"],
            "max_positions": 2,
        },
    )

    result = select_orchestrator_symbols(
        "config.json",
        run_dir=str(run_dir),
        candidate_symbols=["035420.KS", "005930.KS", "000660.KS"],
        symbol_scores={"005930.KS": 0.91, "000660.KS": 0.88, "035420.KS": 0.64},
        selection_reason="opening strength rank",
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["005930.KS", "000660.KS"]
    assert saved["selected_symbols"] == ["005930.KS", "000660.KS"]
    assert saved["symbol_selection"]["selection_reason"] == "opening strength rank"


def test_select_orchestrator_symbols_preserves_order_without_scores(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "source": "auto",
            "interval": "15m",
            "codes": ["005930.KS", "000660.KS", "035420.KS"],
        },
    )

    result = select_orchestrator_symbols(
        "config.json",
        run_dir=str(run_dir),
        candidate_symbols=["035420.KS", "005930.KS"],
        max_positions=1,
    )

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["035420.KS"]


def test_select_orchestrator_symbols_filters_out_non_universe_and_excluded(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "source": "auto",
            "interval": "5m",
            "codes": ["005930.KS", "000660.KS", "035420.KS"],
        },
    )

    result = select_orchestrator_symbols(
        "config.json",
        run_dir=str(run_dir),
        candidate_symbols=["069500.KS", "000660.KS", "035420.KS"],
        exclude_symbols=["000660.KS"],
    )

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["035420.KS"]


def test_select_orchestrator_symbols_rejects_non_positive_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(cfg, {"source": "auto", "interval": "1D", "codes": ["005930.KS"]})

    result = select_orchestrator_symbols(
        "config.json",
        run_dir=str(run_dir),
        max_positions=0,
    )

    assert result["status"] == "error"
