"""Tests for KIS inquire_balance."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.brokers.kis import KISBrokerAdapter


def _adapter() -> KISBrokerAdapter:
    return KISBrokerAdapter(
        app_key="k", app_secret="s",
        account_no="73000000", product_code="01",
        paper_app_key="pk", paper_app_secret="ps",
        default_env="demo",
    )


_OUTPUT1 = [
    {
        "pdno": "005930", "prdt_name": "삼성전자",
        "hldg_qty": "10", "ord_psbl_qty": "10",
        "pchs_avg_pric": "70000", "prpr": "72000",
        "evlu_amt": "720000", "evlu_pfls_amt": "20000", "evlu_pfls_rt": "2.86",
    },
    {
        "pdno": "000660", "prdt_name": "SK하이닉스",
        "hldg_qty": "0", "ord_psbl_qty": "0",   # 수량 0 → 제외돼야 함
        "pchs_avg_pric": "130000", "prpr": "128000",
        "evlu_amt": "0", "evlu_pfls_amt": "0", "evlu_pfls_rt": "0",
    },
]

_OUTPUT2 = {
    "dnca_tot_amt": "1000000",
    "tot_evlu_amt": "1720000",
    "pchs_amt_smtl_amt": "700000",
    "evlu_amt_smtl_amt": "720000",
    "evlu_pfls_smtl_amt": "20000",
    "prft_rate": "2.86",
}


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_holdings(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "rt_cd": "0",
            "output1": _OUTPUT1,
            "output2": _OUTPUT2,
            "ctx_area_fk100": "",
            "ctx_area_nk100": "",
        },
        raise_for_status=lambda: None,
    )

    result = adapter.inquire_balance(env_dv="demo")

    assert result["status"] == "ok"
    assert result["env_dv"] == "demo"

    holdings = result["holdings"]
    # 수량 0인 SK하이닉스는 제외
    assert len(holdings) == 1
    h = holdings[0]
    assert h["symbol"] == "005930"
    assert h["name"] == "삼성전자"
    assert h["qty"] == 10.0
    assert h["tradable_qty"] == 10.0
    assert h["avg_price"] == 70000.0
    assert h["current_price"] == 72000.0
    assert h["eval_amount"] == 720000.0
    assert h["profit_loss"] == 20000.0
    assert h["profit_rate"] == pytest.approx(2.86)


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_summary(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "rt_cd": "0",
            "output1": _OUTPUT1,
            "output2": _OUTPUT2,
            "ctx_area_fk100": "",
            "ctx_area_nk100": "",
        },
        raise_for_status=lambda: None,
    )

    result = adapter.inquire_balance(env_dv="demo")
    s = result["summary"]
    assert s["deposit"] == 1_000_000.0
    assert s["total_eval"] == 1_720_000.0
    assert s["purchase_amt"] == 700_000.0
    assert s["eval_amt"] == 720_000.0
    assert s["profit_loss"] == 20_000.0
    assert s["profit_rate"] == pytest.approx(2.86)


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_no_next_ctx(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "rt_cd": "0", "output1": [], "output2": {},
            "ctx_area_fk100": "", "ctx_area_nk100": "",
        },
        raise_for_status=lambda: None,
    )

    result = adapter.inquire_balance(env_dv="demo")
    assert result["next_ctx"] is None


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_has_next_ctx(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "rt_cd": "0", "output1": [], "output2": {},
            "ctx_area_fk100": "CURSOR_FK", "ctx_area_nk100": "CURSOR_NK",
        },
        raise_for_status=lambda: None,
    )

    result = adapter.inquire_balance(env_dv="demo")
    assert result["next_ctx"] == {"fk": "CURSOR_FK", "nk": "CURSOR_NK"}


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_output2_as_list(mock_token):
    """output2가 리스트로 올 때도 올바르게 파싱."""
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "rt_cd": "0",
            "output1": [],
            "output2": [_OUTPUT2],   # 리스트 형태
            "ctx_area_fk100": "",
            "ctx_area_nk100": "",
        },
        raise_for_status=lambda: None,
    )

    result = adapter.inquire_balance(env_dv="demo")
    assert result["summary"]["deposit"] == 1_000_000.0


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_api_error(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"rt_cd": "1", "msg1": "접근권한 없음"},
        raise_for_status=lambda: None,
    )

    result = adapter.inquire_balance(env_dv="demo")
    assert result["status"] == "error"
    assert "접근권한" in result["error"]


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_tr_id_real(mock_token):
    """실전 환경에서는 TTTC8434R TR_ID 사용."""
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = KISBrokerAdapter(
        app_key="k", app_secret="s",
        account_no="73000000", product_code="01",
        default_env="real",
    )
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"rt_cd": "0", "output1": [], "output2": {}, "ctx_area_fk100": "", "ctx_area_nk100": ""},
        raise_for_status=lambda: None,
    )

    adapter.inquire_balance(env_dv="real")

    call_kwargs = adapter.session.get.call_args
    headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs[0][1]
    assert headers["tr_id"] == "TTTC8434R"


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_inquire_balance_tr_id_demo(mock_token):
    """모의투자 환경에서는 VTTC8434R TR_ID 사용."""
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"rt_cd": "0", "output1": [], "output2": {}, "ctx_area_fk100": "", "ctx_area_nk100": ""},
        raise_for_status=lambda: None,
    )

    adapter.inquire_balance(env_dv="demo")

    call_kwargs = adapter.session.get.call_args
    headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs[0][1]
    assert headers["tr_id"] == "VTTC8434R"
