"""Tests for KIS order execution methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.brokers.kis import KISBrokerAdapter


def _adapter(account_no="73000000", product_code="01") -> KISBrokerAdapter:
    return KISBrokerAdapter(
        app_key="test_key",
        app_secret="test_secret",
        account_no=account_no,
        product_code=product_code,
        paper_app_key="paper_key",
        paper_app_secret="paper_secret",
        default_env="demo",
    )


# ------------------------------------------------------------------
# 호가단위
# ------------------------------------------------------------------

@pytest.mark.parametrize("price,expected", [
    (1000, 1), (1999, 1),
    (2000, 5), (4999, 5),
    (5000, 10), (19999, 10),
    (20000, 50), (49999, 50),
    (50000, 100), (199999, 100),
    (200000, 500), (499999, 500),
    (500000, 1000), (999999, 1000),
])
def test_get_tick_size(price, expected):
    assert KISBrokerAdapter.get_tick_size(price) == expected


def test_round_to_tick():
    assert KISBrokerAdapter.round_to_tick(70123) == 70100   # 50원 단위
    assert KISBrokerAdapter.round_to_tick(232500) == 232500  # 딱 맞음
    assert KISBrokerAdapter.round_to_tick(232300) == 232000  # 500원 단위 내림


# ------------------------------------------------------------------
# 계좌번호 파싱
# ------------------------------------------------------------------

def test_parse_account_plain():
    adapter = _adapter("73000000", "01")
    cano, prod = adapter._parse_account()
    assert cano == "73000000"
    assert prod == "01"


def test_parse_account_with_dash():
    adapter = _adapter("73000000-02")
    cano, prod = adapter._parse_account()
    assert cano == "73000000"
    assert prod == "02"


def test_parse_account_fallback_product_code():
    adapter = _adapter("73000000", "")
    _, prod = adapter._parse_account()
    assert prod == "01"  # 기본값


# ------------------------------------------------------------------
# dry_run 주문
# ------------------------------------------------------------------

def test_place_order_cash_dry_run_buy():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "buy", qty=10, price=232500, dry_run=True)
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["tr_id"] == "VTTC0012U"   # demo 매수
    assert result["ord_dvsn"] == "00"        # 지정가
    assert result["ord_unpr"] == "232500"


def test_place_order_cash_dry_run_sell():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "sell", qty=5, price=0, dry_run=True)
    assert result["tr_id"] == "VTTC0011U"   # demo 매도
    assert result["ord_dvsn"] == "01"        # 시장가


def test_place_order_cash_dry_run_real():
    adapter = KISBrokerAdapter(
        app_key="k", app_secret="s", account_no="73000000",
        product_code="01", default_env="real",
    )
    result = adapter.place_order_cash("005930", "buy", qty=1, price=50000, dry_run=True)
    assert result["tr_id"] == "TTTC0012U"   # real 매수


def test_place_order_cash_invalid_side():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "hold", qty=1, dry_run=True)
    assert result["status"] == "error"


def test_place_order_cash_zero_qty():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "buy", qty=0, dry_run=True)
    assert result["status"] == "error"


# ------------------------------------------------------------------
# 시장가 / 지정가 자동 전환
# ------------------------------------------------------------------

def test_auto_market_when_price_zero():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "buy", qty=1, price=0, order_type="auto", dry_run=True)
    assert result["ord_dvsn"] == "01"
    assert result["ord_unpr"] == "0"


def test_auto_limit_when_price_given():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "buy", qty=1, price=70000, order_type="auto", dry_run=True)
    assert result["ord_dvsn"] == "00"
    assert result["ord_unpr"] == "70000"


def test_force_market_even_with_price():
    adapter = _adapter()
    result = adapter.place_order_cash("005930", "buy", qty=1, price=70000, order_type="market", dry_run=True)
    assert result["ord_dvsn"] == "01"


# ------------------------------------------------------------------
# _rest_post 실제 호출 mocking
# ------------------------------------------------------------------

def _mock_token(adapter: KISBrokerAdapter) -> None:
    adapter._tokens["demo"].__class__ = type(
        "_TokenState", (),
        {"access_token": "fake_token", "expires_at": None}
    )
    adapter._tokens["demo"].access_token = "fake_token"
    from datetime import datetime, timezone, timedelta
    adapter._tokens["demo"].expires_at = datetime.now(timezone.utc) + timedelta(hours=1)


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_rest_post_success(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"rt_cd": "0", "output": {"ODNO": "0001234", "KRX_FWDG_ORD_ORGNO": "91234", "ORD_TMD": "093000"}},
        raise_for_status=lambda: None,
    )

    result = adapter.place_order_cash("005930", "buy", qty=10, price=70000, env_dv="demo")
    assert result["status"] == "ok"
    assert result["order_no"] == "0001234"
    assert result["side"] == "buy"
    assert result["qty"] == 10


@patch("src.brokers.kis.KISBrokerAdapter.issue_access_token")
def test_rest_post_api_error(mock_token):
    mock_token.return_value = {"status": "ok", "access_token": "fake"}
    adapter = _adapter()
    adapter.session = MagicMock()
    adapter.session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"rt_cd": "1", "msg1": "잔고 부족"},
        raise_for_status=lambda: None,
    )

    result = adapter.place_order_cash("005930", "buy", qty=9999, price=70000, env_dv="demo")
    assert result["status"] == "error"
    assert "잔고 부족" in result["error"]


def test_venue_capability_demo_allows_sor_but_not_direct_nxt():
    adapter = _adapter()
    cap = adapter.venue_capability(env_dv="demo")
    assert cap["nxt_quote"] is True
    assert cap["nxt_orderbook"] is True
    assert cap["nxt_balance"] is True
    assert cap["sor_order"] is True
    assert cap["nxt_order"] is False
    assert cap["vts_nxt_supported"] is False


def test_get_nxt_market_context_uses_quote2_nx():
    adapter = _adapter()
    with patch.object(adapter, "_rest_get") as mock_get:
        mock_get.return_value = {
            "status": "ok",
            "body": {
                "output": {
                    "stck_prpr": "70700",
                    "acml_vol": "120000",
                    "acml_tr_pbmn": "8484000000",
                }
            },
        }
        result = adapter.get_nxt_market_context("005930", env_dv="demo")

    assert result["status"] == "ok"
    assert result["nxt_price"] == 70700
    assert result["nxt_volume"] == 120000
    assert result["nxt_turnover"] == 8484000000
    assert mock_get.call_args.kwargs["params"]["FID_COND_MRKT_DIV_CODE"] == "NX"


def test_order_cash_dry_run_sets_exchange_id_sor():
    adapter = _adapter()
    result = adapter.place_order_cash(
        "005930", "buy", qty=1, price=70000,
        excg_id="SOR", env_dv="demo", dry_run=True,
    )
    assert result["body"]["EXCG_ID_DVSN_CD"] == "SOR"


# ------------------------------------------------------------------
# API 스펙 TR_ID 검증
# ------------------------------------------------------------------

def test_cancel_order_uses_correct_tr_id_demo():
    """API 스펙: 모의 정정/취소 TR_ID = VTTC0013U (이전 VTTC0051U 아님)."""
    adapter = _adapter()  # default_env="demo"
    body_sent = {}

    with patch.object(adapter, "_rest_post") as mock_post:
        mock_post.return_value = {
            "status": "ok",
            "body": {"output": {"ODNO": "123", "KRX_FWDG_ORD_ORGNO": "01234"}},
        }
        adapter.cancel_order(
            krx_org_no="01234",
            order_no="0000012345",
            symbol="005930",
            qty=10,
            env_dv="demo",
        )
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["tr_id"] == "VTTC0013U", (
            "모의투자 취소주문 TR_ID는 VTTC0013U여야 합니다"
        )


def test_cancel_order_uses_correct_tr_id_real():
    """API 스펙: 실전 정정/취소 TR_ID = TTTC0013U."""
    adapter = KISBrokerAdapter(
        app_key="k", app_secret="s",
        account_no="73000000", product_code="01",
        default_env="real",
    )
    with patch.object(adapter, "_rest_post") as mock_post:
        mock_post.return_value = {
            "status": "ok",
            "body": {"output": {"ODNO": "123", "KRX_FWDG_ORD_ORGNO": "01234"}},
        }
        adapter.cancel_order(
            krx_org_no="01234",
            order_no="0000012345",
            symbol="005930",
            qty=10,
            env_dv="real",
        )
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["tr_id"] == "TTTC0013U", (
            "실전 취소주문 TR_ID는 TTTC0013U여야 합니다"
        )


def test_volume_ranking_uses_correct_tr_id():
    """API 스펙: 거래량순위 TR_ID = FHPST01710000 (거래대금 FHPST01700000 아님)."""
    adapter = _adapter()
    with patch.object(adapter, "_rest_get") as mock_get:
        mock_get.return_value = {"status": "ok", "body": {"output": []}}
        adapter.get_volume_ranking(market="Q")
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["tr_id"] == "FHPST01710000"


def test_volume_ranking_exls_code_10digits():
    """API 스펙: FID_TRGT_EXLS_CLS_CODE는 10자리여야 한다."""
    adapter = _adapter()
    with patch.object(adapter, "_rest_get") as mock_get:
        mock_get.return_value = {"status": "ok", "body": {"output": []}}
        adapter.get_volume_ranking()
        params = mock_get.call_args[1]["params"]
        exls = params.get("FID_TRGT_EXLS_CLS_CODE", "")
        assert len(exls) == 10, f"FID_TRGT_EXLS_CLS_CODE는 10자리여야 하는데 {len(exls)}자리임"


def test_hts_id_loaded_from_env():
    """hts_id가 from_env()에서 KIS_HTS_ID 환경변수로 로드된다."""
    import os
    from unittest.mock import patch as _patch
    with _patch.dict(os.environ, {
        "KIS_PAPER_APP_KEY": "k", "KIS_PAPER_APP_SECRET": "s",
        "KIS_ACCOUNT_NO": "73000000", "KIS_PRODUCT_CODE": "01",
        "KIS_ENV": "demo", "KIS_HTS_ID": "myhtslogin",
    }):
        a = KISBrokerAdapter.from_env()
        assert a.hts_id == "myhtslogin"
