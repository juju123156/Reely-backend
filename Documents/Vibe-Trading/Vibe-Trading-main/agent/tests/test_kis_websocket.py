"""Tests for KIS WebSocket tick subscriber."""

from __future__ import annotations

import json
from base64 import b64encode
from unittest.mock import MagicMock, patch

import pytest

from src.brokers.kis_websocket import (
    TickData,
    FillNotifyData,
    _aes_cbc_decrypt,
    _parse_tick,
    _parse_orderbook,
    _merge_orderbook_into_tick,
    _parse_fill_notify,
    _FILL_IDX,
    _TICK_COLUMNS,
    _ORDERBOOK_COLUMNS,
    _IDX,
    _OB_IDX,
    KISTickSubscriber,
    make_tick_subscriber,
)


# ------------------------------------------------------------------
# 파싱 유틸
# ------------------------------------------------------------------

def _make_fields(**overrides) -> list[str]:
    """TICK_COLUMNS 길이의 빈 필드 배열 생성, override 적용."""
    fields = [""] * len(_TICK_COLUMNS)
    for col, val in overrides.items():
        fields[_IDX[col]] = str(val)
    return fields


def _make_orderbook_fields(**overrides) -> list[str]:
    fields = [""] * len(_ORDERBOOK_COLUMNS)
    for col, val in overrides.items():
        fields[_OB_IDX[col]] = str(val)
    return fields


def test_parse_tick_basic():
    fields = _make_fields(
        MKSC_SHRN_ISCD="005930",
        STCK_PRPR="72000",
        SHNU_CNTG_SMTN="1500",
        SELN_CNTG_SMTN="1000",
        TOTAL_BIDP_RSQN="2000",
        TOTAL_ASKP_RSQN="1500",
        CNTG_VOL="100",
        STCK_CNTG_HOUR="093015",
    )
    tick = _parse_tick(fields)
    assert tick is not None
    assert tick.symbol == "005930"
    assert tick.price == 72000.0
    assert tick.buy_vol_total == 1500.0
    assert tick.sell_vol_total == 1000.0
    assert tick.bid_qty == 2000.0
    assert tick.ask_qty == 1500.0
    assert tick.tick_vol == 100.0
    assert tick.time == "093015"


def test_parse_tick_too_short():
    fields = [""] * 10  # 40개 미만
    assert _parse_tick(fields) is None


def test_parse_tick_invalid_float():
    fields = _make_fields(
        MKSC_SHRN_ISCD="000660",
        STCK_PRPR="N/A",   # 파싱 불가 → 0.0
        SHNU_CNTG_SMTN="300",
        SELN_CNTG_SMTN="200",
        TOTAL_BIDP_RSQN="100",
        TOTAL_ASKP_RSQN="80",
        CNTG_VOL="",
    )
    tick = _parse_tick(fields)
    assert tick is not None
    assert tick.price == 0.0
    assert tick.tick_vol == 0.0


def test_parse_orderbook_basic():
    fields = _make_orderbook_fields(
        MKSC_SHRN_ISCD="005930",
        BSOP_HOUR="093015",
        ASKP1="72010",
        ASKP_RSQN1="100",
        ASKP2="72020",
        ASKP_RSQN2="200",
        ASKP3="72030",
        ASKP_RSQN3="300",
        BIDP1="72000",
        BIDP_RSQN1="150",
        BIDP2="71990",
        BIDP_RSQN2="250",
        BIDP3="71980",
        BIDP_RSQN3="350",
    )

    book = _parse_orderbook(fields, received_ts=1000.0)

    assert book is not None
    assert book.symbol == "005930"
    assert book.depth_levels_available == 3
    assert book.ask_prices[:2] == [72010.0, 72020.0]
    assert book.bid_qtys[0] == 150.0


def test_parse_orderbook_detects_crossed_book():
    fields = _make_orderbook_fields(
        MKSC_SHRN_ISCD="005930",
        ASKP1="72000",
        ASKP_RSQN1="100",
        BIDP1="72010",
        BIDP_RSQN1="100",
    )

    book = _parse_orderbook(fields, received_ts=1000.0)

    assert book is not None
    assert book.invalid_reason == "bid_ask_crossed"
    assert book.depth_levels_available == 0


def test_merge_orderbook_into_tick_fresh_and_stale():
    tick = _parse_tick(_make_fields(MKSC_SHRN_ISCD="005930", STCK_PRPR="72000"))
    assert tick is not None
    book = _parse_orderbook(_make_orderbook_fields(
        MKSC_SHRN_ISCD="005930",
        ASKP1="72010",
        ASKP_RSQN1="100",
        BIDP1="72000",
        BIDP_RSQN1="150",
    ), received_ts=1000.0)

    fresh = _merge_orderbook_into_tick(tick, book, now=1000.5)
    stale = _merge_orderbook_into_tick(tick, book, now=1004.5)

    assert fresh.orderbook_stale is False
    assert fresh.orderbook_quality == "fresh"
    assert fresh.ask1_qty == 100.0
    assert stale.orderbook_stale is True
    assert stale.orderbook_quality == "stale"


# ------------------------------------------------------------------
# 데이터 메시지 파싱 (_handle_data)
# ------------------------------------------------------------------

def _build_raw_tick(**kwargs) -> str:
    """0|H0STCNT0|001|field1^field2^... 형식 문자열 생성."""
    fields = _make_fields(**kwargs)
    data = "^".join(fields)
    return f"0|H0STCNT0|001|{data}"


def _make_subscriber(on_tick=None) -> KISTickSubscriber:
    return KISTickSubscriber(
        app_key="k", app_secret="s",
        base_url="https://fake", ws_url="ws://fake",
        symbols=["005930"],
        on_tick=on_tick or (lambda t: None),
    )


def test_handle_data_fires_callback():
    received = []
    sub = _make_subscriber(on_tick=received.append)
    raw = _build_raw_tick(
        MKSC_SHRN_ISCD="005930", STCK_PRPR="72000",
        SHNU_CNTG_SMTN="1200", SELN_CNTG_SMTN="800",
        TOTAL_BIDP_RSQN="1000", TOTAL_ASKP_RSQN="900",
        CNTG_VOL="50",
    )
    sub._handle_data(raw)
    assert len(received) == 1
    assert received[0].symbol == "005930"
    assert received[0].price == 72000.0


def test_handle_data_wrong_tr_id_ignored():
    received = []
    sub = _make_subscriber(on_tick=received.append)
    raw = "0|UNKNOWN|001|some^data"
    sub._handle_data(raw)
    assert len(received) == 0


def test_handle_data_merges_cached_orderbook_into_tick():
    received = []
    sub = _make_subscriber(on_tick=received.append)
    fields = _make_orderbook_fields(
        MKSC_SHRN_ISCD="005930",
        ASKP1="72010",
        ASKP_RSQN1="100",
        BIDP1="72000",
        BIDP_RSQN1="150",
    )
    sub._handle_data(f"0|H0STASP0|001|{'^'.join(fields)}")
    sub._handle_data(_build_raw_tick(MKSC_SHRN_ISCD="005930", STCK_PRPR="72000"))

    assert len(received) == 1
    assert received[0].depth_levels_available == 1
    assert received[0].orderbook_stale is False
    assert received[0].ask1_price == 72010.0


def test_handle_data_too_few_parts_ignored():
    received = []
    sub = _make_subscriber(on_tick=received.append)
    sub._handle_data("0|H0STCNT0")  # parts < 4
    assert len(received) == 0


# ------------------------------------------------------------------
# 시스템 메시지 처리 (_handle_system)
# ------------------------------------------------------------------

def test_handle_system_saves_aes_key():
    sub = _make_subscriber()
    msg = json.dumps({
        "header": {"tr_id": "H0STCNT0", "encrypt": "Y"},
        "body": {
            "rt_cd": "0",
            "msg1": "SUBSCRIBE SUCCESS",
            "output": {"iv": "1234567890123456", "key": "A" * 32},
        },
    })
    sub._handle_system(msg)
    assert sub._aes.get("H0STCNT0") == {"iv": "1234567890123456", "key": "A" * 32}


def test_handle_system_subscribe_ok_no_crash():
    sub = _make_subscriber()
    msg = json.dumps({
        "header": {"tr_id": "H0STCNT0", "encrypt": "N"},
        "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"},
    })
    sub._handle_system(msg)   # no exception


def test_handle_system_invalid_json_ignored():
    sub = _make_subscriber()
    sub._handle_system("not json")  # no exception


# ------------------------------------------------------------------
# AES 복호화
# ------------------------------------------------------------------

def test_aes_cbc_decrypt():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    from base64 import b64encode

    key = "A" * 32
    iv  = "B" * 16
    plaintext = "hello^world^test"

    cipher = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
    encrypted_b64 = b64encode(cipher.encrypt(pad(plaintext.encode(), AES.block_size))).decode()

    result = _aes_cbc_decrypt(key, iv, encrypted_b64)
    assert result == plaintext


def test_aes_cbc_decrypt_bad_key_raises():
    with pytest.raises(Exception):
        _aes_cbc_decrypt(None, None, "aabbcc==")


# ------------------------------------------------------------------
# 암호화된 데이터 처리
# ------------------------------------------------------------------

def test_handle_data_encrypted_decrypts_correctly():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    key = "K" * 32
    iv  = "I" * 16

    fields = _make_fields(
        MKSC_SHRN_ISCD="005930", STCK_PRPR="75000",
        SHNU_CNTG_SMTN="999", SELN_CNTG_SMTN="777",
        TOTAL_BIDP_RSQN="500", TOTAL_ASKP_RSQN="400",
        CNTG_VOL="10",
    )
    plaintext = "^".join(fields).encode()
    cipher = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
    encrypted_b64 = b64encode(cipher.encrypt(pad(plaintext, AES.block_size))).decode()

    received = []
    sub = _make_subscriber(on_tick=received.append)
    sub._aes["H0STCNT0"] = {"key": key, "iv": iv}

    raw = f"1|H0STCNT0|001|{encrypted_b64}"
    sub._handle_data(raw)

    assert len(received) == 1
    assert received[0].symbol == "005930"
    assert received[0].price == 75000.0


def test_handle_data_encrypted_no_key_skipped():
    received = []
    sub = _make_subscriber(on_tick=received.append)
    # AES key not set → skip
    raw = "1|H0STCNT0|001|someciphertext"
    sub._handle_data(raw)
    assert len(received) == 0


# ------------------------------------------------------------------
# make_tick_subscriber 팩토리
# ------------------------------------------------------------------

def test_make_tick_subscriber_demo():
    from src.brokers.kis import KISBrokerAdapter
    adapter = KISBrokerAdapter(
        app_key="rk", app_secret="rs",
        account_no="73000000", product_code="01",
        paper_app_key="pk", paper_app_secret="ps",
        paper_base_url="https://demo.kis.com",
        default_env="demo",
    )
    sub = make_tick_subscriber(adapter, ["005930"], lambda t: None, env="demo")
    assert sub._app_key == "pk"
    assert sub._app_secret == "ps"
    assert "31000" in sub._ws_url or "21000" in sub._ws_url


def test_make_tick_subscriber_real():
    from src.brokers.kis import KISBrokerAdapter
    adapter = KISBrokerAdapter(
        app_key="rk", app_secret="rs",
        account_no="73000000", product_code="01",
        default_env="real",
    )
    sub = make_tick_subscriber(adapter, ["005930"], lambda t: None, env="real")
    assert sub._app_key == "rk"
    assert "21000" in sub._ws_url


def test_make_tick_subscriber_wrong_type():
    with pytest.raises(TypeError):
        make_tick_subscriber(object(), ["005930"], lambda t: None)


# ------------------------------------------------------------------
# WS 러너 통합 — use_ws=True 시 _ws_loop 기동 확인
# ------------------------------------------------------------------

def test_runner_ws_mode_non_kis_returns_error():
    from src.trading.kr_order_flow_runner import KROrderFlowRunner
    runner = KROrderFlowRunner()
    result = runner.start(
        broker_name="kiwoom",
        symbols=["005930"],
        use_ws=True,
    )
    assert result["task"]["status"] == "error"
    assert "KIS" in result["task"]["last_error"]


# ------------------------------------------------------------------
# H0STCNI9 체결통보 파싱 (API 스펙 필드 인덱스 검증)
# ------------------------------------------------------------------

def _make_fill_fields(
    cust_id="myhtsid",
    acnt_no="1234567801",
    oder_no="0000002891",
    ooder_no="",
    seln_byov_cls="02",   # 02=매수
    rctf_cls="0",
    oder_kind="00",
    oder_cond="0",
    stck_shrn_iscd="136480",
    cntg_qty="5",
    cntg_unpr="3190",
    stck_cntg_hour="094941",
    rfus_yn="0",
    cntg_yn="2",          # 2=체결
    acpt_yn="2",
    brnc_no="06010",
    oder_qty="5",
    acnt_name="김한투",
    extra="",
) -> list[str]:
    """API 스펙 순서대로 H0STCNI9 필드 배열 생성."""
    return [
        cust_id, acnt_no, oder_no, ooder_no, seln_byov_cls,
        rctf_cls, oder_kind, oder_cond, stck_shrn_iscd,
        cntg_qty, cntg_unpr, stck_cntg_hour, rfus_yn, cntg_yn,
        acpt_yn, brnc_no, oder_qty, acnt_name, extra,
    ]


def test_parse_fill_notify_buy():
    """매수 체결통보 파싱 — 필드 인덱스 스펙 준수."""
    fields = _make_fill_fields(seln_byov_cls="02", cntg_qty="10", cntg_unpr="3500")
    fill = _parse_fill_notify(fields)
    assert fill is not None
    assert fill.side == "buy"
    assert fill.qty == 10
    assert fill.price == 3500.0
    assert fill.order_no == "0000002891"
    assert fill.symbol == "136480"


def test_parse_fill_notify_sell():
    """매도 체결통보 파싱."""
    fields = _make_fill_fields(seln_byov_cls="01", cntg_qty="5", cntg_unpr="3200")
    fill = _parse_fill_notify(fields)
    assert fill is not None
    assert fill.side == "sell"
    assert fill.qty == 5
    assert fill.price == 3200.0


def test_parse_fill_notify_ignores_order_acceptance():
    """CNTG_YN=1 (주문접수) 통보는 무시해야 한다."""
    fields = _make_fill_fields(cntg_yn="1", cntg_qty="10", cntg_unpr="3500")
    fill = _parse_fill_notify(fields)
    assert fill is None


def test_parse_fill_notify_ignores_rejected():
    """RFUS_YN=1 (거부) 통보는 무시해야 한다."""
    fields = _make_fill_fields(rfus_yn="1", cntg_qty="10", cntg_unpr="3500")
    fill = _parse_fill_notify(fields)
    assert fill is None


def test_parse_fill_notify_too_short():
    """필드 수 부족 시 None 반환."""
    assert _parse_fill_notify(["a"] * 5) is None


def test_fill_idx_cntg_yn_is_13():
    """API 스펙: CNTG_YN은 14번째 값(0-index=13)."""
    assert _FILL_IDX["CNTG_YN"] == 13


def test_fill_idx_stck_shrn_iscd_is_8():
    """API 스펙: 종목코드(STCK_SHRN_ISCD)는 9번째 값(0-index=8)."""
    assert _FILL_IDX["PDNO"] == 8


def test_make_tick_subscriber_uses_hts_id():
    """make_tick_subscriber는 hts_id가 있으면 account_no 대신 사용."""
    from unittest.mock import MagicMock
    from src.brokers.kis import KISBrokerAdapter
    adapter = KISBrokerAdapter(
        paper_app_key="k", paper_app_secret="s",
        account_no="73000000", hts_id="my_hts_login",
        default_env="demo",
    )
    sub = make_tick_subscriber(adapter, symbols=[], on_tick=lambda t: None, env="demo")
    assert sub._account_no == "my_hts_login"


def test_make_tick_subscriber_falls_back_to_account_no():
    """hts_id가 없으면 account_no로 폴백."""
    from src.brokers.kis import KISBrokerAdapter
    adapter = KISBrokerAdapter(
        paper_app_key="k", paper_app_secret="s",
        account_no="73000000", hts_id="",
        default_env="demo",
    )
    sub = make_tick_subscriber(adapter, symbols=[], on_tick=lambda t: None, env="demo")
    assert sub._account_no == "73000000"
