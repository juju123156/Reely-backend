from __future__ import annotations

import json
from pathlib import Path

from src.trading.orchestrator_runner import prepare_orchestrator_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_prepare_orchestrator_config_sets_mode_and_selected_symbols(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "source": "auto",
            "interval": "1D",
            "codes": ["005930.KS", "000660.KS"],
        },
    )

    result = prepare_orchestrator_config(
        "config.json",
        run_dir=str(run_dir),
        mode="paper",
        selected_symbols=["005930.KS"],
        strategy_id="kr-breakout-01",
        strategy_version="v1",
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert saved["mode"] == "paper"
    assert saved["selected_symbols"] == ["005930.KS"]
    assert saved["strategy_id"] == "kr-breakout-01"
    assert saved["strategy_version"] == "v1"


def test_prepare_orchestrator_config_adds_exit_policy_for_kr_intraday(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "source": "auto",
            "interval": "5m",
            "codes": ["091990.KQ"],
        },
    )

    result = prepare_orchestrator_config(
        "config.json",
        run_dir=str(run_dir),
        mode="live",
        selected_symbols=["091990.KQ"],
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert saved["exit_policy"]["stop_loss"] == "-1.2%"
    assert saved["exit_policy"]["fallback_rule"] == "if no signal then time_stop"


def test_prepare_orchestrator_config_keeps_selected_symbols_empty_when_not_provided(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "source": "auto",
            "interval": "15m",
            "codes": ["005930.KS"],
        },
    )

    result = prepare_orchestrator_config(
        "config.json",
        run_dir=str(run_dir),
        mode="paper",
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert saved["selected_symbols"] == []


def test_prepare_orchestrator_config_rejects_bad_mode(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(cfg, {"source": "auto", "interval": "1D", "codes": ["005930.KS"]})

    result = prepare_orchestrator_config(
        "config.json",
        run_dir=str(run_dir),
        mode="invalid",
    )
    assert result["status"] == "error"
