from __future__ import annotations

import json
from pathlib import Path

from src.trading.paper_state import validate_exit_policy, write_paper_mode_artifacts


def _base_config(**overrides):
    config = {
        "mode": "paper",
        "interval": "5m",
        "codes": ["005930.KS", "000660.KS"],
        "selected_symbols": ["005930.KS"],
        "strategy_id": "kr-open-001",
        "symbol_selection": {
            "candidate_symbols": ["005930.KS", "000660.KS", "035420.KS"],
            "ranked_symbols": ["005930.KS", "000660.KS", "035420.KS"],
            "selected_symbols": ["005930.KS"],
            "scores": {"005930.KS": 0.91, "000660.KS": 0.88},
            "selection_reason": "opening strength rank",
        },
        "exit_policy": {
            "signal_exit": "VWAP breakdown",
            "stop_loss": "-1.2%",
            "take_profit": "+2.5%",
            "time_stop": "10:30 force exit",
            "fallback_rule": "if no signal then time_stop",
        },
    }
    config.update(overrides)
    return config


def _write_metrics(run_dir: Path, *, trade_count: int = 25, max_drawdown: float = 0.05) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "metrics.csv").write_text(
        "final_value,total_return,annual_return,max_drawdown,sharpe,win_rate,trade_count\n"
        f"1100000,0.1,0.1,{max_drawdown},1.2,0.55,{trade_count}\n",
        encoding="utf-8",
    )


def test_validate_exit_policy_requires_fallback_for_kr_intraday_paper() -> None:
    config = _base_config(exit_policy={"stop_loss": "-1.2%"})
    err = validate_exit_policy(config)
    assert err is not None
    assert "take_profit" in err or "time_stop" in err or "fallback_rule" in err


def test_validate_exit_policy_skips_research_mode() -> None:
    config = _base_config(mode="research", exit_policy={})
    assert validate_exit_policy(config) is None


def test_write_paper_mode_artifacts_creates_three_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_metrics(run_dir)
    outputs = write_paper_mode_artifacts(run_dir, _base_config())

    assert set(outputs.keys()) == {"risk_report", "trade_decision", "execution_plan", "execution_history"}
    for path in outputs.values():
        assert path.exists()

    trade_decision = json.loads(outputs["trade_decision"].read_text(encoding="utf-8"))
    risk_report = json.loads(outputs["risk_report"].read_text(encoding="utf-8"))
    execution_plan = json.loads(outputs["execution_plan"].read_text(encoding="utf-8"))
    execution_history = json.loads(outputs["execution_history"].read_text(encoding="utf-8"))

    assert trade_decision["decision"] == "BUY"
    assert trade_decision["exit_policy"]["time_stop"] == "10:30 force exit"
    assert trade_decision["symbol_scores"]["005930.KS"] == 0.91
    assert trade_decision["entry_signal_snapshot"]["selection_reason"] == "opening strength rank"
    assert trade_decision["entry_signal_snapshot"]["ranked_candidates"][0]["symbol"] == "005930.KS"
    assert trade_decision["entry_signal_snapshot"]["top_ranked_not_selected"] == ["000660.KS", "035420.KS"]
    assert risk_report["status"] == "PASS"
    assert execution_plan["ready"] is True
    assert execution_plan["orders"][0]["selection_score"] == 0.91
    assert execution_history[0]["selected_symbols"] == ["005930.KS"]
    assert execution_history[0]["entry_signal_snapshot"]["rejected_symbols"] == ["000660.KS", "035420.KS"]
    assert execution_history[0]["exit_policy_snapshot"]["time_stop"] == "10:30 force exit"


def test_write_paper_mode_artifacts_blocks_when_metrics_fail(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_metrics(run_dir, trade_count=3, max_drawdown=0.35)
    outputs = write_paper_mode_artifacts(run_dir, _base_config(max_drawdown_limit=0.2))

    trade_decision = json.loads(outputs["trade_decision"].read_text(encoding="utf-8"))
    risk_report = json.loads(outputs["risk_report"].read_text(encoding="utf-8"))
    execution_plan = json.loads(outputs["execution_plan"].read_text(encoding="utf-8"))

    assert trade_decision["decision"] == "HOLD"
    assert risk_report["status"] == "FAIL"
    assert execution_plan["ready"] is False


def test_write_paper_mode_artifacts_appends_execution_history(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_metrics(run_dir)

    first = write_paper_mode_artifacts(run_dir, _base_config())
    second = write_paper_mode_artifacts(run_dir, _base_config(selected_symbols=["000660.KS"]))

    history_rows = json.loads(second["execution_history"].read_text(encoding="utf-8"))
    assert len(history_rows) == 2
    assert history_rows[0]["selected_symbols"] == ["005930.KS"]
    assert history_rows[1]["selected_symbols"] == ["000660.KS"]
