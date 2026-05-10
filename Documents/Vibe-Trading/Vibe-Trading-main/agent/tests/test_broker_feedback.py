from __future__ import annotations

import json
from pathlib import Path

from src.trading.broker_feedback import sync_broker_feedback
from src.trading.paper_state import write_paper_mode_artifacts


def _base_config() -> dict:
    return {
        "mode": "paper",
        "interval": "5m",
        "codes": ["005930.KS", "000660.KS"],
        "selected_symbols": ["005930.KS"],
        "strategy_id": "kr-open-001",
        "symbol_selection": {
            "candidate_symbols": ["005930.KS", "000660.KS"],
            "ranked_symbols": ["005930.KS", "000660.KS"],
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


def _write_metrics(run_dir: Path) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "metrics.csv").write_text(
        "final_value,total_return,annual_return,max_drawdown,sharpe,win_rate,trade_count\n"
        "1100000,0.1,0.1,0.05,1.2,0.55,25\n",
        encoding="utf-8",
    )


def test_sync_broker_feedback_updates_latest_execution_history(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_metrics(run_dir)
    write_paper_mode_artifacts(run_dir, _base_config())

    result = sync_broker_feedback(
        run_dir,
        broker="kiwoom",
        execution_result={"results": [{"order_id": "1234567"}]},
        orders={"orders": [{"ord_no": "1234567"}]},
        fills={"fills": [{"ord_no": "1234567", "exec_qty": "2"}]},
    )

    assert result["status"] == "ok"
    history = json.loads((run_dir / "artifacts" / "execution_history.json").read_text(encoding="utf-8"))
    latest = history[-1]
    assert latest["broker"] == "kiwoom"
    assert latest["open_order_count"] == 1
    assert latest["fill_count"] == 1
    assert latest["broker_fills"]["fills"][0]["ord_no"] == "1234567"
