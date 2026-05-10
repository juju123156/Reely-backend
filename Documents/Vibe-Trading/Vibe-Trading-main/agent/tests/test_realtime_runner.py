from __future__ import annotations

import json
import time
from pathlib import Path

from src.trading.realtime_runner import RealtimeBrokerRunnerManager


class _FakeBroker:
    def __init__(self) -> None:
        self.calls = 0

    def build_quote_subscription(self, symbols, quote_types=None, market_code="KRX"):
        return {
            "trnm": "REG",
            "data": [{"item": list(symbols), "type": quote_types or ["0B"]}],
            "market_code": market_code,
        }

    def run_websocket_roundtrip(self, payloads, *, env_dv=None, receive_count=1, timeout=5.0):
        self.calls += 1
        return {
            "status": "ok",
            "messages": [
                {"trnm": "LOGIN", "return_code": 0},
                {
                    "trnm": "REAL",
                    "data": [
                        {"stk_cd": "000660.KS", "flu_rt": "1.25"},
                        {"stk_cd": "005930.KS", "flu_rt": "0.71"},
                    ],
                },
            ],
        }


def test_realtime_runner_updates_config_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.json"
    config_path.write_text(
        json.dumps({"codes": ["005930.KS", "000660.KS"], "max_positions": 1}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fake = _FakeBroker()
    monkeypatch.setattr("src.trading.realtime_runner.get_broker_adapter", lambda name: fake)

    manager = RealtimeBrokerRunnerManager()
    result = manager.start(
        broker_name="kiwoom",
        run_dir=str(run_dir),
        path="config.json",
        symbols=["005930.KS", "000660.KS"],
        max_positions=1,
        selection_reason="background realtime loop",
        poll_interval=0.01,
        max_cycles=1,
    )

    task_id = result["task"]["task_id"]
    for _ in range(50):
        status = manager.status(task_id)
        if status["task"]["status"] in {"completed", "error"}:
            break
        time.sleep(0.02)

    status = manager.status(task_id)
    assert status["task"]["status"] == "completed"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["selected_symbols"] == ["000660.KS"]
    assert (run_dir / "artifacts" / "realtime_broker_messages.json").exists()
    assert (run_dir / "artifacts" / "realtime_symbol_scores.json").exists()


def test_realtime_runner_can_be_stopped(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps({"codes": ["005930.KS"]}), encoding="utf-8")

    fake = _FakeBroker()
    monkeypatch.setattr("src.trading.realtime_runner.get_broker_adapter", lambda name: fake)

    manager = RealtimeBrokerRunnerManager()
    result = manager.start(
        broker_name="kiwoom",
        run_dir=str(run_dir),
        path="config.json",
        symbols=["005930.KS"],
        poll_interval=0.2,
    )
    task_id = result["task"]["task_id"]
    stopped = manager.stop(task_id)
    assert stopped["status"] == "ok"
