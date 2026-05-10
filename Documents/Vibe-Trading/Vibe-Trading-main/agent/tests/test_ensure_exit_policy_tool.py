from __future__ import annotations

import json
from pathlib import Path

from src.tools.ensure_exit_policy_tool import ensure_exit_policy


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_ensure_exit_policy_autofills_kr_intraday_paper(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "mode": "paper",
            "interval": "5m",
            "codes": ["005930.KS"],
            "source": "auto",
        },
    )

    result = ensure_exit_policy("config.json", run_dir=str(run_dir))
    assert result["status"] == "ok"
    assert result["updated"] is True

    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["exit_policy"]["stop_loss"] == "-1.2%"
    assert saved["exit_policy"]["time_stop"] == "10:30 force exit"


def test_ensure_exit_policy_preserves_existing_values(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "mode": "paper",
            "interval": "15m",
            "codes": ["005930.KS"],
            "source": "auto",
            "exit_policy": {
                "stop_loss": "-0.8%",
                "time_stop": "11:00 force exit",
            },
        },
    )

    result = ensure_exit_policy("config.json", run_dir=str(run_dir))
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert saved["exit_policy"]["stop_loss"] == "-0.8%"
    assert saved["exit_policy"]["time_stop"] == "11:00 force exit"
    assert saved["exit_policy"]["take_profit"] == "+2.5%"


def test_ensure_exit_policy_skips_non_intraday_or_non_paper(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "mode": "research",
            "interval": "1D",
            "codes": ["005930.KS"],
            "source": "auto",
        },
    )

    result = ensure_exit_policy("config.json", run_dir=str(run_dir))
    assert result["status"] == "ok"
    assert result["updated"] is False


def test_ensure_exit_policy_accepts_overrides(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = run_dir / "config.json"
    _write_config(
        cfg,
        {
            "mode": "live",
            "interval": "5m",
            "codes": ["091990.KQ"],
            "source": "auto",
        },
    )

    result = ensure_exit_policy(
        "config.json",
        run_dir=str(run_dir),
        overrides={"time_stop": "10:45 force exit", "fallback_rule": "if no signal then 10:45 exit"},
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert saved["exit_policy"]["time_stop"] == "10:45 force exit"
    assert saved["exit_policy"]["fallback_rule"] == "if no signal then 10:45 exit"
