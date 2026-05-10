from __future__ import annotations

import json
from pathlib import Path

from src.trading.realtime_selection import apply_realtime_selection_update


def test_apply_realtime_selection_update_writes_artifact_and_updates_config(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "codes": ["005930.KS", "000660.KS", "035420.KS"],
                "max_positions": 2,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    messages = [
        {
            "data": [
                {"stk_cd": "005930.KS", "flu_rt": "0.71"},
                {"stk_cd": "000660.KS", "flu_rt": "1.25"},
                {"stk_cd": "035420.KS", "flu_rt": "-0.40"},
            ]
        }
    ]

    result = apply_realtime_selection_update(
        "config.json",
        run_dir=str(run_dir),
        messages=messages,
        max_positions=2,
        selection_reason="kiwoom realtime strength",
    )

    assert result["status"] == "ok"
    assert result["selected_symbols"] == ["000660.KS", "005930.KS"]
    assert Path(result["ranking_artifact"]).exists()

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["selected_symbols"] == ["000660.KS", "005930.KS"]
    assert config["symbol_selection"]["selection_reason"] == "kiwoom realtime strength"
