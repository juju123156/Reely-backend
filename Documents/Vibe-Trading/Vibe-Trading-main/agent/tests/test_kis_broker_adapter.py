from __future__ import annotations

from pathlib import Path

from src.brokers.kis import KISBrokerAdapter


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeSession:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def post(self, url: str, json: dict, headers: dict, timeout: float) -> _FakeResponse:
        self.post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResponse(
            {
                "access_token": "token-123",
                "access_token_token_expired": "2026-04-26 23:59:59",
            }
        )

    def get(self, url: str, headers: dict, params: dict, timeout: float) -> _FakeResponse:
        self.get_calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        if url.endswith("/inquire-price"):
            return _FakeResponse(
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70500",
                        "stck_oprc": "70000",
                        "stck_hgpr": "70600",
                        "stck_lwpr": "69800",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8712345",
                        "prdy_vrss": "500",
                        "prdy_ctrt": "0.71",
                        "stck_cntg_hour": "091500",
                    },
                }
            )
        return _FakeResponse(
            {
                "rt_cd": "0",
                "output1": {
                    "stck_bsop_date": "20260426",
                },
                "output2": [
                    {
                        "stck_bsop_date": "20260426",
                        "stck_cntg_hour": "090100",
                        "stck_oprc": "70000",
                        "stck_hgpr": "70100",
                        "stck_lwpr": "69900",
                        "stck_prpr": "70050",
                        "cntg_vol": "100",
                    },
                    {
                        "stck_bsop_date": "20260426",
                        "stck_cntg_hour": "090200",
                        "stck_oprc": "70050",
                        "stck_hgpr": "70200",
                        "stck_lwpr": "70000",
                        "stck_prpr": "70150",
                        "cntg_vol": "200",
                    },
                    {
                        "stck_bsop_date": "20260426",
                        "stck_cntg_hour": "090300",
                        "stck_oprc": "70150",
                        "stck_hgpr": "70300",
                        "stck_lwpr": "70100",
                        "stck_prpr": "70250",
                        "cntg_vol": "300",
                    },
                    {
                        "stck_bsop_date": "20260426",
                        "stck_cntg_hour": "090400",
                        "stck_oprc": "70250",
                        "stck_hgpr": "70400",
                        "stck_lwpr": "70200",
                        "stck_prpr": "70350",
                        "cntg_vol": "400",
                    },
                    {
                        "stck_bsop_date": "20260426",
                        "stck_cntg_hour": "090500",
                        "stck_oprc": "70350",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "70300",
                        "stck_prpr": "70450",
                        "cntg_vol": "500",
                    },
                    {
                        "stck_bsop_date": "20260426",
                        "stck_cntg_hour": "090600",
                        "stck_oprc": "70450",
                        "stck_hgpr": "70600",
                        "stck_lwpr": "70400",
                        "stck_prpr": "70550",
                        "cntg_vol": "600",
                    },
                ],
            }
        )


def _build_adapter(session: _FakeSession | None = None) -> KISBrokerAdapter:
    return KISBrokerAdapter(
        app_key="real-app",
        app_secret="real-secret",
        account_no="12345678",
        product_code="01",
        paper_app_key="paper-app",
        paper_app_secret="paper-secret",
        session=session or _FakeSession(),
    )


def test_issue_access_token_uses_cache() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    first = adapter.issue_access_token()
    second = adapter.issue_access_token()

    assert first["status"] == "ok"
    assert second["cached"] is True
    assert len(session.post_calls) == 1


def test_get_quote_standardizes_kis_payload() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    result = adapter.get_quote("005930.KS")

    assert result["status"] == "ok"
    assert result["symbol"] == "005930"
    assert result["quote"]["last"] == 70500.0
    assert result["quote"]["volume"] == 123456.0
    assert result["raw"]["stck_prpr"] == "70500"


def test_get_intraday_bars_resamples_to_5m() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    result = adapter.get_intraday_bars("005930.KS", "5m", "090000", "090600")

    assert result["status"] == "ok"
    assert result["interval"] == "5m"
    assert len(result["bars"]) == 2
    first = result["bars"][0]
    second = result["bars"][1]
    assert first["timestamp"].endswith("09:00:00")
    assert first["open"] == 70000.0
    assert first["high"] == 70400.0
    assert first["low"] == 69900.0
    assert first["close"] == 70350.0
    assert first["volume"] == 1000.0
    assert second["timestamp"].endswith("09:05:00")
    assert second["close"] == 70550.0
