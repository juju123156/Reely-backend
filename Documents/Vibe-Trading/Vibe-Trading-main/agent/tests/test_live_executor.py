from __future__ import annotations

import json
from pathlib import Path

from src.trading.live_executor import execute_broker_plan


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_execute_broker_plan_requires_ready_plan(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "artifacts" / "execution_plan.json", {"mode": "paper", "ready": False, "orders": [], "broker": "kis"})
    _write_json(run_dir / "artifacts" / "trade_decision.json", {"decision": "BUY"})

    result = execute_broker_plan(str(run_dir))
    assert result["status"] == "error"
    assert "not ready" in result["error"]


def test_execute_broker_plan_simulates_kis_paper(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "artifacts" / "execution_plan.json",
        {
            "mode": "paper",
            "ready": True,
            "broker": "kis",
            "orders": [{"symbol": "005930.KS", "side": "BUY", "qty_policy": "equal_weight", "limit_policy": "marketable_limit", "time_in_force": "DAY", "selection_score": 0.91}],
            "entry_signal_snapshot": {"selected_symbols": ["005930.KS"]},
            "exit_policy_snapshot": {"time_stop": "10:30 force exit"},
        },
    )
    _write_json(
        run_dir / "artifacts" / "trade_decision.json",
        {"decision": "BUY", "strategy_id": "kr-open", "strategy_version": "v1"},
    )
    monkeypatch.setenv("KIS_APP_KEY", "app")
    monkeypatch.setenv("KIS_APP_SECRET", "sec")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")

    result = execute_broker_plan(str(run_dir))

    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["results"][0]["accepted"] is True
    assert Path(result["artifact"]).exists()


def test_execute_broker_plan_blocks_live_without_confirmation(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "artifacts" / "execution_plan.json",
        {"mode": "live", "ready": True, "broker": "kiwoom", "orders": [{"symbol": "005930.KS", "side": "BUY", "qty_policy": "equal_weight"}]},
    )
    _write_json(run_dir / "artifacts" / "trade_decision.json", {"decision": "BUY"})
    monkeypatch.setenv("KIWOOM_APP_KEY", "app")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "sec")
    monkeypatch.setenv("KIWOOM_ACCOUNT_NO", "12345678")

    result = execute_broker_plan(str(run_dir))
    assert result["status"] == "error"
    assert "confirm_live" in result["error"]


def test_execute_broker_plan_submits_live_kiwoom_order(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "artifacts" / "execution_plan.json",
        {
            "mode": "live",
            "ready": True,
            "broker": "kiwoom",
            "orders": [
                {
                    "symbol": "005930.KS",
                    "side": "BUY",
                    "qty_policy": "fixed",
                    "quantity": 2,
                    "limit_policy": "market",
                    "market_code": "KRX",
                }
            ],
        },
    )
    _write_json(run_dir / "artifacts" / "trade_decision.json", {"decision": "BUY"})
    monkeypatch.setenv("KIWOOM_APP_KEY", "app")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "sec")
    monkeypatch.setenv("KIWOOM_ACCOUNT_NO", "12345678")

    from src.brokers.kiwoom import KiwoomBrokerAdapter

    original_from_env = KiwoomBrokerAdapter.from_env

    class _LiveFakeResponse:
        def __init__(self, payload: dict, status_code: int = 200) -> None:
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def json(self) -> dict:
            return self._payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    class _LiveFakeSession:
        def post(self, url: str, json: dict, headers: dict, timeout: float) -> _LiveFakeResponse:
            if url.endswith("/oauth2/token"):
                return _LiveFakeResponse({"token": "kw", "expires_dt": "20260426235959", "return_code": 0, "return_msg": "ok"})
            return _LiveFakeResponse({"return_code": 0, "return_msg": "ok", "ord_no": "7654321", "dmst_stex_tp": "KRX"})

    monkeypatch.setattr(
        KiwoomBrokerAdapter,
        "from_env",
        classmethod(lambda cls: KiwoomBrokerAdapter(app_key="app", secret_key="sec", account_no="12345678", session=_LiveFakeSession())),
    )
    try:
        result = execute_broker_plan(str(run_dir), confirm_live=True)
    finally:
        monkeypatch.setattr(KiwoomBrokerAdapter, "from_env", original_from_env)

    assert result["status"] == "ok"
    assert result["dry_run"] is False
    assert result["results"][0]["accepted"] is True
    assert result["results"][0]["order_id"] == "7654321"
    assert Path(result["broker_feedback_artifact"]).exists()
