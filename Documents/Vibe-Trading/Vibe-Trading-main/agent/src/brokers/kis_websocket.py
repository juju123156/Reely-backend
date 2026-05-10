"""KIS WebSocket 실시간 체결 틱 구독 클라이언트.

H0STCNT0 (국내주식 실시간체결가, KRX) 스트림을 받아
OrderFlowState.update_poll() 에 필요한 필드를 콜백으로 전달한다.

의존성:
  websockets>=12.0
  pycryptodome>=3.20.0  (AES-CBC 복호화)

WebSocket 프로토콜 개요 (KIS):
  1. REST POST /oauth2/Approval → approval_key (access token 과 별개)
  2. ws://ops.koreainvestment.com:21000 연결
  3. 구독 메시지 JSON 전송 (tr_type="1")
  4. 시스템 응답(JSON): 구독 확인 + AES 키(encrypt="Y" 일 때)
  5. 틱 데이터: "0|H0STCNT0|001|field^field^..." (^-구분, 암호화 시 "1|...")
  6. PINGPONG: JSON {"header":{"tr_id":"PINGPONG"}} → ws.pong() 응답
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from base64 import b64decode
from dataclasses import dataclass, replace
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 상수
# ------------------------------------------------------------------

PROD_WS_URL = "ws://ops.koreainvestment.com:21000"
DEMO_WS_URL = "ws://ops.koreainvestment.com:31000"

TR_ID_TICK = "H0STCNT0"
TR_ID_ORDERBOOK = "H0STASP0"
TR_ID_FILL = "H0STCNI9"   # 국내주식 실시간 체결통보
ORDERBOOK_FRESH_SEC = 1.0
ORDERBOOK_TTL_SEC = 3.0

# H0STCNT0 컬럼 (인덱스 기반 파싱용)
_TICK_COLUMNS = [
    "MKSC_SHRN_ISCD",       # 0  종목코드
    "STCK_CNTG_HOUR",       # 1  체결시간(HHMMSS)
    "STCK_PRPR",             # 2  현재가
    "PRDY_VRSS_SIGN",       # 3  전일대비부호
    "PRDY_VRSS",             # 4  전일대비
    "PRDY_CTRT",             # 5  전일대비율
    "WGHN_AVRG_STCK_PRC",  # 6  가중평균주가
    "STCK_OPRC",             # 7  시가
    "STCK_HGPR",             # 8  고가
    "STCK_LWPR",             # 9  저가
    "ASKP1",                 # 10 매도호가1
    "BIDP1",                 # 11 매수호가1
    "CNTG_VOL",              # 12 체결거래량(이번 틱)
    "ACML_VOL",              # 13 누적거래량
    "ACML_TR_PBMN",         # 14 누적거래대금
    "SELN_CNTG_CSNU",       # 15 매도체결건수
    "SHNU_CNTG_CSNU",       # 16 매수체결건수
    "NTBY_CNTG_CSNU",       # 17 순매수체결건수
    "CTTR",                  # 18 체결강도
    "SELN_CNTG_SMTN",       # 19 총매도수량(누적)
    "SHNU_CNTG_SMTN",       # 20 총매수수량(누적)
    "CCLD_DVSN",             # 21 체결구분
    "SHNU_RATE",             # 22 매수비율
    "PRDY_VOL_VRSS_ACML_VOL_RATE",  # 23 전일거래량대비등락율
    "OPRC_HOUR",             # 24 시가시간
    "OPRC_VRSS_PRPR_SIGN",  # 25 시가대비현재가부호
    "OPRC_VRSS_PRPR",       # 26 시가대비현재가
    "HGPR_HOUR",             # 27 최고가시간
    "HGPR_VRSS_PRPR_SIGN",  # 28 최고가대비현재가부호
    "HGPR_VRSS_PRPR",       # 29 최고가대비현재가
    "LWPR_HOUR",             # 30 최저가시간
    "LWPR_VRSS_PRPR_SIGN",  # 31 최저가대비현재가부호
    "LWPR_VRSS_PRPR",       # 32 최저가대비현재가
    "BSOP_DATE",             # 33 영업일자
    "NEW_MKOP_CLS_CODE",    # 34 신장운영구분코드
    "TRHT_YN",               # 35 거래정지여부
    "ASKP_RSQN1",            # 36 매도호가잔량1
    "BIDP_RSQN1",            # 37 매수호가잔량1
    "TOTAL_ASKP_RSQN",      # 38 총매도호가잔량
    "TOTAL_BIDP_RSQN",      # 39 총매수호가잔량
    "VOL_TNRT",              # 40 거래량회전율
    "PRDY_SMNS_HOUR_ACML_VOL",       # 41 전일동시간누적거래량
    "PRDY_SMNS_HOUR_ACML_VOL_RATE",  # 42 전일동시간누적거래량비율
    "HOUR_CLS_CODE",         # 43 시간구분코드
    "MRKT_TRTM_CLS_CODE",   # 44 임의종료구분코드
    "VI_STND_PRC",           # 45 정적VI발동기준가
]

# 우리가 필요한 인덱스만 명시
_IDX = {col: i for i, col in enumerate(_TICK_COLUMNS)}

# H0STASP0 국내주식 실시간호가. KIS Developers 문서 버전에 따라 부가 필드가
# 뒤에 붙을 수 있으므로, 실행 중 payload 길이는 별도 로그로 검증해야 한다.
_ORDERBOOK_COLUMNS = (
    ["MKSC_SHRN_ISCD", "BSOP_HOUR", "HOUR_CLS_CODE"]
    + [f"ASKP{i}" for i in range(1, 11)]
    + [f"BIDP{i}" for i in range(1, 11)]
    + [f"ASKP_RSQN{i}" for i in range(1, 11)]
    + [f"BIDP_RSQN{i}" for i in range(1, 11)]
    + ["TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN"]
)
_OB_IDX = {col: i for i, col in enumerate(_ORDERBOOK_COLUMNS)}


# ------------------------------------------------------------------
# 데이터 모델
# ------------------------------------------------------------------

@dataclass
class TickData:
    """H0STCNT0 틱 1건 — ScalpingBot.enqueue_tick() 입력."""
    symbol: str
    price: float
    buy_vol_total: float    # SHNU_CNTG_SMTN (누적 매수 체결 수량)
    sell_vol_total: float   # SELN_CNTG_SMTN (누적 매도 체결 수량)
    bid_qty: float          # TOTAL_BIDP_RSQN
    ask_qty: float          # TOTAL_ASKP_RSQN
    tick_vol: float         # CNTG_VOL (이번 틱 거래량)
    time: str               # STCK_CNTG_HOUR
    acml_vol: float = 0.0        # ACML_VOL      — 누적 거래량 (VWAP용)
    acml_tr_pbmn: float = 0.0    # ACML_TR_PBMN  — 누적 거래대금 (VWAP용)
    ask1_price: float = 0.0      # ASKP1         — 매도1호가 (스프레드/진입가)
    bid1_price: float = 0.0      # BIDP1         — 매수1호가 (청산가)
    ask1_qty: float = 0.0
    bid1_qty: float = 0.0
    ask2_price: float = 0.0
    ask2_qty: float = 0.0
    bid2_price: float = 0.0
    bid2_qty: float = 0.0
    ask3_price: float = 0.0
    ask3_qty: float = 0.0
    bid3_price: float = 0.0
    bid3_qty: float = 0.0
    ask4_price: float = 0.0
    ask4_qty: float = 0.0
    bid4_price: float = 0.0
    bid4_qty: float = 0.0
    ask5_price: float = 0.0
    ask5_qty: float = 0.0
    bid5_price: float = 0.0
    bid5_qty: float = 0.0
    ask6_price: float = 0.0
    ask6_qty: float = 0.0
    bid6_price: float = 0.0
    bid6_qty: float = 0.0
    ask7_price: float = 0.0
    ask7_qty: float = 0.0
    bid7_price: float = 0.0
    bid7_qty: float = 0.0
    ask8_price: float = 0.0
    ask8_qty: float = 0.0
    bid8_price: float = 0.0
    bid8_qty: float = 0.0
    ask9_price: float = 0.0
    ask9_qty: float = 0.0
    bid9_price: float = 0.0
    bid9_qty: float = 0.0
    ask10_price: float = 0.0
    ask10_qty: float = 0.0
    bid10_price: float = 0.0
    bid10_qty: float = 0.0
    orderbook_source_ts: float = 0.0
    orderbook_received_ts: float = 0.0
    orderbook_age_sec: float = 999.0
    depth_levels_available: int = 1
    orderbook_stale: bool = True
    orderbook_quality: str = "fallback"
    invalid_orderbook: bool = False
    orderbook_invalid_reason: str = ""
    is_vi: bool = False           # VI 발동 여부 (VI_STND_PRC != "0")


@dataclass
class OrderbookData:
    symbol: str
    bid_prices: list[float]
    bid_qtys: list[float]
    ask_prices: list[float]
    ask_qtys: list[float]
    source_ts: float
    received_ts: float
    depth_levels_available: int
    raw: dict | None = None
    invalid_reason: str = ""


@dataclass
class FillNotifyData:
    """H0STCNI9 체결통보 1건 — OrderExecutor.on_fill_notify() 입력."""
    order_no: str
    symbol: str
    side: str    # "buy" | "sell"
    qty: int
    price: float


# H0STCNI9 필드 인덱스 (^ 구분, KIS 국내주식 실시간체결통보)
# 순서: CUST_ID(0) ACNT_NO(1) ODER_NO(2) OODER_NO(3) SELN_BYOV_CLS(4)
#       RCTF_CLS(5) ODER_KIND(6) ODER_COND(7) STCK_SHRN_ISCD(8)
#       CNTG_QTY(9) CNTG_UNPR(10) STCK_CNTG_HOUR(11) RFUS_YN(12)
#       CNTG_YN(13) ACPT_YN(14) ...
_FILL_IDX = {
    "ODER_NO":       2,   # 주문번호
    "SELN_BYOV_CLS": 4,   # 매도매수구분 (01=매도, 02=매수)
    "PDNO":          8,   # 종목코드 (STCK_SHRN_ISCD)
    "CNTG_QTY":      9,   # 체결수량
    "CNTG_UNPR":     10,  # 체결단가
    "RFUS_YN":       12,  # 거부여부 (0=승인, 1=거부)
    "CNTG_YN":       13,  # 체결여부 (1=주문/정정/취소/거부, 2=체결)
}


# ------------------------------------------------------------------
# AES 복호화 (pycryptodome)
# ------------------------------------------------------------------

def _aes_cbc_decrypt(key: str, iv: str, cipher_b64: str) -> str:
    try:
        from Crypto.Cipher import AES as _AES
        from Crypto.Util.Padding import unpad as _unpad
    except ImportError as exc:
        raise ImportError("pycryptodome 필요: pip install pycryptodome") from exc

    cipher = _AES.new(key.encode("utf-8"), _AES.MODE_CBC, iv.encode("utf-8"))
    return bytes.decode(_unpad(cipher.decrypt(b64decode(cipher_b64)), _AES.block_size))


# ------------------------------------------------------------------
# 파싱 헬퍼
# ------------------------------------------------------------------

def _to_float(v: str) -> float:
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def _source_ts_from_hhmmss(value: str) -> float:
    if not value or len(value) < 6:
        return 0.0
    now = time.localtime()
    try:
        hour = int(value[0:2])
        minute = int(value[2:4])
        second = int(value[4:6])
        return time.mktime((
            now.tm_year, now.tm_mon, now.tm_mday,
            hour, minute, second,
            now.tm_wday, now.tm_yday, now.tm_isdst,
        ))
    except Exception:
        return 0.0


def _parse_tick(fields: list[str]) -> TickData | None:
    if len(fields) < 40:
        return None
    try:
        # HOUR_CLS_CODE == "C" → VI발동 (API 스펙: C=9시이후예상가+VI발동)
        # VI_STND_PRC는 정적VI기준가격(가격 숫자)이므로 VI 여부 판단 불가
        hour_cls = fields[_IDX["HOUR_CLS_CODE"]] if len(fields) > _IDX["HOUR_CLS_CODE"] else "0"
        return TickData(
            symbol=fields[_IDX["MKSC_SHRN_ISCD"]],
            price=_to_float(fields[_IDX["STCK_PRPR"]]),
            buy_vol_total=_to_float(fields[_IDX["SHNU_CNTG_SMTN"]]),
            sell_vol_total=_to_float(fields[_IDX["SELN_CNTG_SMTN"]]),
            bid_qty=_to_float(fields[_IDX["TOTAL_BIDP_RSQN"]]),
            ask_qty=_to_float(fields[_IDX["TOTAL_ASKP_RSQN"]]),
            tick_vol=_to_float(fields[_IDX["CNTG_VOL"]]),
            time=fields[_IDX["STCK_CNTG_HOUR"]],
            acml_vol=_to_float(fields[_IDX["ACML_VOL"]]),
            acml_tr_pbmn=_to_float(fields[_IDX["ACML_TR_PBMN"]]),
            ask1_price=_to_float(fields[_IDX["ASKP1"]]),
            bid1_price=_to_float(fields[_IDX["BIDP1"]]),
            ask1_qty=_to_float(fields[_IDX["ASKP_RSQN1"]]),
            bid1_qty=_to_float(fields[_IDX["BIDP_RSQN1"]]),
            is_vi=(hour_cls == "C"),
        )
    except Exception:
        return None


def _parse_orderbook(fields: list[str], *, received_ts: float | None = None) -> OrderbookData | None:
    if len(fields) < len(_ORDERBOOK_COLUMNS):
        return None
    try:
        symbol = fields[_OB_IDX["MKSC_SHRN_ISCD"]]
        if not symbol:
            return None
        ask_prices: list[float] = []
        bid_prices: list[float] = []
        ask_qtys: list[float] = []
        bid_qtys: list[float] = []
        for level in range(1, 11):
            ask_price = _to_float(fields[_OB_IDX[f"ASKP{level}"]])
            bid_price = _to_float(fields[_OB_IDX[f"BIDP{level}"]])
            ask_qty = _to_float(fields[_OB_IDX[f"ASKP_RSQN{level}"]])
            bid_qty = _to_float(fields[_OB_IDX[f"BIDP_RSQN{level}"]])
            if ask_price > 0 and ask_qty > 0:
                ask_prices.append(ask_price)
                ask_qtys.append(ask_qty)
            if bid_price > 0 and bid_qty > 0:
                bid_prices.append(bid_price)
                bid_qtys.append(bid_qty)

        depth = min(len(ask_prices), len(bid_prices), len(ask_qtys), len(bid_qtys))
        source_ts = _source_ts_from_hhmmss(fields[_OB_IDX["BSOP_HOUR"]])
        now = received_ts if received_ts is not None else time.time()
        invalid_reason = ""
        if depth < 1:
            invalid_reason = "empty_depth"
        elif bid_prices[0] >= ask_prices[0]:
            invalid_reason = "bid_ask_crossed"

        return OrderbookData(
            symbol=symbol,
            bid_prices=bid_prices[:depth],
            bid_qtys=bid_qtys[:depth],
            ask_prices=ask_prices[:depth],
            ask_qtys=ask_qtys[:depth],
            source_ts=source_ts,
            received_ts=now,
            depth_levels_available=depth if not invalid_reason else 0,
            raw={
                "field_count": len(fields),
                "total_ask_qty": _to_float(fields[_OB_IDX["TOTAL_ASKP_RSQN"]]),
                "total_bid_qty": _to_float(fields[_OB_IDX["TOTAL_BIDP_RSQN"]]),
            },
            invalid_reason=invalid_reason,
        )
    except Exception:
        return None


def _merge_orderbook_into_tick(tick: TickData, book: OrderbookData | None, *, now: float | None = None) -> TickData:
    if not book or book.invalid_reason:
        reason = book.invalid_reason if book else "missing_orderbook"
        return replace(
            tick,
            orderbook_age_sec=999.0,
            depth_levels_available=1,
            orderbook_stale=True,
            orderbook_quality="fallback",
            invalid_orderbook=bool(book and book.invalid_reason),
            orderbook_invalid_reason=reason,
        )
    current_ts = now if now is not None else time.time()
    age = max(0.0, current_ts - book.received_ts)
    quality = "fresh" if age <= ORDERBOOK_FRESH_SEC else "degraded" if age <= ORDERBOOK_TTL_SEC else "stale"
    values: dict[str, Any] = {
        "orderbook_source_ts": book.source_ts,
        "orderbook_received_ts": book.received_ts,
        "orderbook_age_sec": age,
        "depth_levels_available": book.depth_levels_available,
        "orderbook_stale": age > ORDERBOOK_TTL_SEC,
        "orderbook_quality": quality,
        "invalid_orderbook": False,
        "orderbook_invalid_reason": "",
    }
    if age <= ORDERBOOK_TTL_SEC:
        for idx in range(10):
            level = idx + 1
            if idx < len(book.ask_prices):
                values[f"ask{level}_price"] = book.ask_prices[idx]
                values[f"ask{level}_qty"] = book.ask_qtys[idx]
            if idx < len(book.bid_prices):
                values[f"bid{level}_price"] = book.bid_prices[idx]
                values[f"bid{level}_qty"] = book.bid_qtys[idx]
        if book.ask_prices:
            values["ask1_price"] = book.ask_prices[0]
            values["ask1_qty"] = book.ask_qtys[0]
        if book.bid_prices:
            values["bid1_price"] = book.bid_prices[0]
            values["bid1_qty"] = book.bid_qtys[0]
    else:
        values["depth_levels_available"] = 1
    return replace(tick, **values)


def _parse_fill_notify(fields: list[str]) -> FillNotifyData | None:
    """H0STCNI9 체결통보 파싱.

    CNTG_YN(index 13) == "2" 인 건만 실제 체결로 처리.
    주문·정정·취소·거부 접수 통보(CNTG_YN="1")는 무시.
    """
    if len(fields) < 14:
        return None
    try:
        # 체결 통보만 처리 (1=주문접수, 2=체결)
        if fields[_FILL_IDX["CNTG_YN"]] != "2":
            return None
        # 거부된 주문 무시
        if fields[_FILL_IDX["RFUS_YN"]] != "0":
            return None

        raw_side = fields[_FILL_IDX["SELN_BYOV_CLS"]]
        side = "buy" if raw_side == "02" else "sell"
        qty = int(fields[_FILL_IDX["CNTG_QTY"]] or "0")
        price = _to_float(fields[_FILL_IDX["CNTG_UNPR"]])
        if qty <= 0 or price <= 0:
            return None
        return FillNotifyData(
            order_no=fields[_FILL_IDX["ODER_NO"]],
            symbol=fields[_FILL_IDX["PDNO"]],
            side=side,
            qty=qty,
            price=price,
        )
    except Exception:
        return None


# ------------------------------------------------------------------
# KISTickSubscriber
# ------------------------------------------------------------------

TickCallback = Callable[[TickData], None]
FillNotifyCallback = Callable[[FillNotifyData], None]


class KISTickSubscriber:
    """KIS H0STCNT0 WebSocket 구독자.

    사용 예::

        sub = KISTickSubscriber(
            app_key="...", app_secret="...",
            symbols=["005930", "000660"],
            on_tick=lambda tick: print(tick),
            env="demo",  # "real" or "demo"
        )
        sub.start_background()   # 데몬 스레드로 실행
        sub.stop()               # 종료
    """

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        base_url: str,
        ws_url: str,
        symbols: list[str],
        on_tick: TickCallback,
        on_fill_notify: FillNotifyCallback | None = None,
        account_no: str = "",    # H0STCNI9 구독 tr_key (HTS_ID 또는 계좌번호)
        max_retries: int = 10,
        retry_delay: float = 3.0,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._base_url = base_url
        self._ws_url = ws_url
        self._symbols = list(symbols)
        self._on_tick = on_tick
        self._on_fill_notify = on_fill_notify
        self._account_no = account_no
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        self._approval_key: str = ""
        self._aes: dict[str, dict[str, str]] = {}  # tr_id → {key, iv}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_orderbook: dict[str, OrderbookData] = {}

    # ----------------------------------------------------------------
    # 공개 API
    # ----------------------------------------------------------------

    def start_background(self) -> None:
        """데몬 스레드에서 WebSocket 루프 시작."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_sync, daemon=True)
        self._thread.start()
        logger.info("KISTickSubscriber started: symbols=%s ws=%s", self._symbols, self._ws_url)

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("KISTickSubscriber stop requested")

    def add_symbol(self, symbol: str) -> None:
        if symbol not in self._symbols:
            self._symbols.append(symbol)

    def remove_symbol(self, symbol: str) -> None:
        self._symbols = [s for s in self._symbols if s != symbol]
        self._latest_orderbook.pop(symbol, None)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ----------------------------------------------------------------
    # WebSocket 접속키 발급
    # ----------------------------------------------------------------

    def _issue_approval_key(self) -> str:
        url = f"{self._base_url}/oauth2/Approval"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "secretkey": self._app_secret,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            key = resp.json().get("approval_key", "")
            if not key:
                raise ValueError(f"approval_key 없음: {resp.text[:200]}")
            logger.info("KIS WS approval key issued")
            return key
        except Exception as exc:
            raise RuntimeError(f"KIS approval key 발급 실패: {exc}") from exc

    # ----------------------------------------------------------------
    # 구독 메시지 생성
    # ----------------------------------------------------------------

    def _subscribe_msg(self, tr_id: str, tr_key: str, tr_type: str = "1") -> str:
        return json.dumps({
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": tr_type,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": tr_key,
                }
            },
        })

    # ----------------------------------------------------------------
    # 메시지 처리
    # ----------------------------------------------------------------

    def _handle_system(self, raw: str) -> None:
        """JSON 시스템 메시지 파싱 — AES 키 저장."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        hdr = msg.get("header") or {}
        body = msg.get("body") or {}
        tr_id = hdr.get("tr_id", "")
        encrypt = hdr.get("encrypt", "N")
        rt_cd = body.get("rt_cd")
        msg1 = body.get("msg1", "")

        output = body.get("output") or {}
        iv = output.get("iv")
        key = output.get("key")
        if iv and key:
            self._aes[tr_id] = {"iv": iv, "key": key}
            logger.debug("AES key saved for tr_id=%s encrypt=%s", tr_id, encrypt)

        if rt_cd == "0":
            logger.info("WS subscribe ok: tr_id=%s msg=%s", tr_id, msg1)
        elif tr_id == "PINGPONG":
            pass  # handled in async loop
        else:
            logger.debug("WS sys msg: tr_id=%s rt_cd=%s msg=%s", tr_id, rt_cd, msg1)

    def _handle_data(self, raw: str) -> None:
        """파이프 구분 실시간 데이터 파싱 (H0STCNT0 틱 + H0STCNI9 체결통보)."""
        parts = raw.split("|")
        if len(parts) < 4:
            return

        encrypted = parts[0] == "1"
        tr_id = parts[1]
        # parts[2] = 건수 (보통 "001")
        data_str = parts[3]

        if encrypted:
            aes = self._aes.get(tr_id)
            if not aes:
                logger.warning("AES key not found for tr_id=%s, skipping", tr_id)
                return
            try:
                data_str = _aes_cbc_decrypt(aes["key"], aes["iv"], data_str)
            except Exception as exc:
                logger.error("AES decrypt error: %s", exc)
                return

        if tr_id == TR_ID_ORDERBOOK:
            fields = data_str.split("^")
            n_cols = len(_ORDERBOOK_COLUMNS)
            n_records = max(1, len(fields) // n_cols)
            now = time.time()
            for i in range(n_records):
                chunk = fields[i * n_cols: (i + 1) * n_cols]
                book = _parse_orderbook(chunk, received_ts=now)
                if book:
                    self._latest_orderbook[book.symbol] = book
                    if book.invalid_reason:
                        logger.warning(
                            "Invalid orderbook: %s reason=%s field_count=%d",
                            book.symbol, book.invalid_reason, len(chunk),
                        )

        elif tr_id == TR_ID_TICK:
            # H0STCNT0: 한 메시지에 여러 틱 가능 (건수 초과 시)
            fields = data_str.split("^")
            n_cols = len(_TICK_COLUMNS)
            n_records = max(1, len(fields) // n_cols)
            now = time.time()
            self._cleanup_orderbook_cache(now)
            for i in range(n_records):
                chunk = fields[i * n_cols: (i + 1) * n_cols]
                tick = _parse_tick(chunk)
                if tick:
                    tick = _merge_orderbook_into_tick(tick, self._latest_orderbook.get(tick.symbol), now=now)
                    try:
                        self._on_tick(tick)
                    except Exception as exc:
                        logger.error("on_tick callback error: %s", exc)

        elif tr_id == TR_ID_FILL and self._on_fill_notify:
            # H0STCNI9: 체결통보 (건당 1건)
            fields = data_str.split("^")
            fill = _parse_fill_notify(fields)
            if fill:
                try:
                    self._on_fill_notify(fill)
                except Exception as exc:
                    logger.error("on_fill_notify callback error: %s", exc)

    def _cleanup_orderbook_cache(self, now: float | None = None) -> None:
        current_ts = now if now is not None else time.time()
        expired = [
            symbol for symbol, book in self._latest_orderbook.items()
            if current_ts - book.received_ts > ORDERBOOK_TTL_SEC * 2
        ]
        for symbol in expired:
            self._latest_orderbook.pop(symbol, None)

    # ----------------------------------------------------------------
    # Async loop
    # ----------------------------------------------------------------

    async def _loop(self) -> None:
        try:
            import websockets as _ws
        except ImportError as exc:
            raise ImportError("websockets 필요: pip install websockets") from exc

        self._approval_key = self._issue_approval_key()
        retries = 0

        while not self._stop_event.is_set():
            try:
                async with _ws.connect(
                    self._ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    retries = 0
                    logger.info("KIS WS connected: %s", self._ws_url)

                    # H0STCNT0 (틱 데이터) 구독
                    for sym in list(self._symbols):
                        await ws.send(self._subscribe_msg(TR_ID_TICK, sym, "1"))
                        await asyncio.sleep(0.05)
                        await ws.send(self._subscribe_msg(TR_ID_ORDERBOOK, sym, "1"))
                        await asyncio.sleep(0.05)

                    # H0STCNI9 (체결통보) 구독 — account_no 제공 시
                    if self._account_no and self._on_fill_notify:
                        await ws.send(self._subscribe_msg(TR_ID_FILL, self._account_no, "1"))
                        logger.info("H0STCNI9 fill notify subscribed (account=%s...)", self._account_no[:4])

                    async for raw in ws:
                        if self._stop_event.is_set():
                            break

                        if not isinstance(raw, str):
                            continue

                        if raw[0] in ("0", "1"):
                            self._handle_data(raw)
                        else:
                            self._handle_system(raw)
                            if '"PINGPONG"' in raw:
                                await ws.pong(raw)

            except Exception as exc:
                if self._stop_event.is_set():
                    break
                retries += 1
                if retries > self._max_retries:
                    logger.error("KIS WS max retries exceeded, giving up")
                    break
                logger.warning("KIS WS error (retry %d/%d): %s", retries, self._max_retries, exc)
                await asyncio.sleep(self._retry_delay)

        logger.info("KIS WS loop exited")

    def _run_sync(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._loop())
        finally:
            loop.close()


# ------------------------------------------------------------------
# 팩토리 — KISBrokerAdapter 인스턴스에서 생성
# ------------------------------------------------------------------

def make_tick_subscriber(
    adapter: Any,
    symbols: list[str],
    on_tick: TickCallback,
    on_fill_notify: FillNotifyCallback | None = None,
    env: str = "demo",
) -> KISTickSubscriber:
    """KISBrokerAdapter 인스턴스로부터 KISTickSubscriber 를 생성한다.

    Args:
        adapter         : KISBrokerAdapter 인스턴스
        symbols         : 구독할 종목 코드 목록
        on_tick         : 틱 콜백 (TickData) -> None
        on_fill_notify  : 체결통보 콜백 (FillNotifyData) -> None (선택)
        env             : "demo" or "real"
    """
    from src.brokers.kis import PROD_BASE_URL, DEMO_BASE_URL, KISBrokerAdapter

    if not isinstance(adapter, KISBrokerAdapter):
        raise TypeError("KISBrokerAdapter 인스턴스가 필요합니다")

    normalized = adapter._normalize_env(env)
    if normalized == "demo":
        app_key = adapter.paper_app_key
        app_secret = adapter.paper_app_secret
        base_url = adapter.paper_base_url or DEMO_BASE_URL
        ws_url = DEMO_WS_URL
    else:
        app_key = adapter.app_key
        app_secret = adapter.app_secret
        base_url = adapter.base_url or PROD_BASE_URL
        ws_url = PROD_WS_URL

    # H0STCNI9 tr_key는 HTS ID (계좌번호가 아님). hts_id 없으면 account_no 폴백.
    hts_id = getattr(adapter, "hts_id", "") or ""
    account_no = getattr(adapter, "account_no", "") or ""
    fill_key = hts_id or account_no

    return KISTickSubscriber(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        ws_url=ws_url,
        symbols=symbols,
        on_tick=on_tick,
        on_fill_notify=on_fill_notify,
        account_no=fill_key,
    )
