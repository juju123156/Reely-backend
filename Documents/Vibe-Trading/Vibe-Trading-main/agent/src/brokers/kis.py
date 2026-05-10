"""KIS broker adapter with token, quote, and intraday market data support."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from src.brokers.base import BrokerAdapter, BrokerExecutionResult, BrokerOrderRequest

_TOKEN_CACHE_DIR = Path.home() / ".cache" / "vibe_trading" / "kis_tokens"


PROD_BASE_URL = "https://openapi.koreainvestment.com:9443"
DEMO_BASE_URL = "https://openapivts.koreainvestment.com:29443"
DEFAULT_WEBSOCKET_URL = "ws://210.107.75.79:21000"
KST = timedelta(hours=9)


@dataclass
class _TokenState:
    access_token: str = ""
    expires_at: datetime | None = None


class KISBrokerAdapter(BrokerAdapter):
    name = "kis"
    supports_live = False
    supports_paper = True

    def __init__(
        self,
        *,
        app_key: str = "",
        app_secret: str = "",
        account_no: str = "",
        product_code: str = "",
        hts_id: str = "",
        base_url: str = "",
        websocket_url: str = "",
        paper_app_key: str = "",
        paper_app_secret: str = "",
        paper_base_url: str = "",
        default_env: str = "real",
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.product_code = product_code
        self.hts_id = hts_id
        self.base_url = base_url or PROD_BASE_URL
        self.paper_app_key = paper_app_key
        self.paper_app_secret = paper_app_secret
        self.paper_base_url = paper_base_url or DEMO_BASE_URL
        self.websocket_url = websocket_url or DEFAULT_WEBSOCKET_URL
        self.default_env = self._normalize_env(default_env)
        self.session = session or requests.Session()
        self.timeout = timeout
        self._tokens: dict[str, _TokenState] = {"real": _TokenState(), "demo": _TokenState()}

    @classmethod
    def from_env(cls) -> "KISBrokerAdapter":
        return cls(
            app_key=os.getenv("KIS_APP_KEY", ""),
            app_secret=os.getenv("KIS_APP_SECRET", ""),
            account_no=os.getenv("KIS_ACCOUNT_NO", ""),
            product_code=os.getenv("KIS_PRODUCT_CODE", ""),
            hts_id=os.getenv("KIS_HTS_ID", ""),
            base_url=os.getenv("KIS_BASE_URL", ""),
            websocket_url=os.getenv("KIS_WS_URL", ""),
            paper_app_key=os.getenv("KIS_PAPER_APP_KEY", ""),
            paper_app_secret=os.getenv("KIS_PAPER_APP_SECRET", ""),
            paper_base_url=os.getenv("KIS_PAPER_BASE_URL", ""),
            default_env=os.getenv("KIS_ENV", "real"),
        )

    def check_connection(self) -> dict[str, Any]:
        missing = [
            key
            for key, value in {
                "KIS_APP_KEY": self.app_key,
                "KIS_APP_SECRET": self.app_secret,
                "KIS_ACCOUNT_NO": self.account_no,
            }.items()
            if not value
        ]
        return {
            "broker": self.name,
            "status": "ok" if not missing else "error",
            "supports_live": self.supports_live,
            "supports_paper": self.supports_paper,
            "missing_env": missing,
            "default_env": self.default_env,
            "paper_credentials_ready": bool(self.paper_app_key and self.paper_app_secret),
            "base_url": self.base_url,
            "paper_base_url": self.paper_base_url,
            "websocket_url": self.websocket_url,
            "message": (
                "KIS adapter ready for REST token, quote, and intraday bar lookup. "
                "Order execution remains scaffolded."
            ),
        }

    def issue_access_token(self, *, env_dv: str | None = None, force: bool = False) -> dict[str, Any]:
        env = self._normalize_env(env_dv)
        state = self._tokens[env]

        # 1) 인메모리 캐시 유효하면 즉시 반환
        if not force and self._token_is_valid(state):
            return {
                "status": "ok",
                "env_dv": env,
                "cached": True,
                "access_token": state.access_token,
                "expires_at": state.expires_at.isoformat() if state.expires_at else "",
            }

        # 2) 디스크 캐시 확인 (KIS는 동일 앱키로 24h 이내 재발급 시 403)
        app_key, app_secret = self._credentials_for_env(env)
        if not app_key or not app_secret:
            return {
                "status": "error",
                "env_dv": env,
                "error": f"missing KIS credentials for env '{env}'",
                "required_env": (
                    ["KIS_APP_KEY", "KIS_APP_SECRET"]
                    if env == "real"
                    else ["KIS_PAPER_APP_KEY", "KIS_PAPER_APP_SECRET"]
                ),
            }

        if not force:
            cached = self._load_token_cache(env, app_key)
            if cached and self._token_is_valid(cached):
                self._tokens[env] = cached
                return {
                    "status": "ok",
                    "env_dv": env,
                    "cached": True,
                    "access_token": cached.access_token,
                    "expires_at": cached.expires_at.isoformat() if cached.expires_at else "",
                }

        # 3) KIS API 호출로 신규 발급
        url = f"{self._base_url_for_env(env)}/oauth2/tokenP"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "charset": "UTF-8",
        }
        payload = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret,
        }
        try:
            response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            return {"status": "error", "env_dv": env, "error": str(exc), "url": url}
        except ValueError as exc:
            return {"status": "error", "env_dv": env, "error": f"invalid token response: {exc}", "url": url}

        token = str(body.get("access_token") or "").strip()
        if not token:
            return {
                "status": "error",
                "env_dv": env,
                "error": "access_token missing from KIS response",
                "raw": body,
            }

        expires_at = self._parse_token_expiry(body) or (self._now_kst() + timedelta(hours=23))
        new_state = _TokenState(access_token=token, expires_at=expires_at)
        self._tokens[env] = new_state
        self._save_token_cache(env, app_key, new_state)
        return {
            "status": "ok",
            "env_dv": env,
            "cached": False,
            "access_token": token,
            "expires_at": expires_at.isoformat(),
            "raw": body,
        }

    def _token_cache_path(self, env: str, app_key: str) -> Path:
        key_suffix = app_key[-8:] if len(app_key) >= 8 else app_key
        return _TOKEN_CACHE_DIR / f"token_{env}_{key_suffix}.json"

    def _save_token_cache(self, env: str, app_key: str, state: _TokenState) -> None:
        try:
            _TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._token_cache_path(env, app_key)
            path.write_text(json.dumps({
                "access_token": state.access_token,
                "expires_at": state.expires_at.isoformat() if state.expires_at else "",
            }), encoding="utf-8")
        except Exception:
            pass  # 캐시 실패는 무시

    def _load_token_cache(self, env: str, app_key: str) -> _TokenState | None:
        try:
            path = self._token_cache_path(env, app_key)
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            token = str(data.get("access_token") or "")
            exp_str = str(data.get("expires_at") or "")
            if not token or not exp_str:
                return None
            expires_at = datetime.fromisoformat(exp_str)
            return _TokenState(access_token=token, expires_at=expires_at)
        except Exception:
            return None

    def get_quote(
        self,
        symbol: str,
        market_code: str = "J",
        *,
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol)
        response = self._rest_get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": normalized_symbol,
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized_symbol}

        body = response["body"]
        output = body.get("output") or {}
        return {
            "status": "ok",
            "broker": self.name,
            "env_dv": response["env_dv"],
            "symbol": normalized_symbol,
            "market_code": market_code,
            "quote": {
                "last": self._to_float(output.get("stck_prpr")),
                "open": self._to_float(output.get("stck_oprc")),
                "high": self._to_float(output.get("stck_hgpr")),
                "low": self._to_float(output.get("stck_lwpr")),
                "volume": self._to_float(output.get("acml_vol")),
                "turnover": self._to_float(output.get("acml_tr_pbmn")),
                "change": self._to_float(output.get("prdy_vrss")),
                "change_rate": self._to_float(output.get("prdy_ctrt")),
                "timestamp": str(output.get("stck_cntg_hour") or ""),
            },
            "raw": output,
        }

    def get_execution_detail(
        self,
        symbol: str,
        *,
        env_dv: str | None = None,
        market_code: str = "J",
    ) -> dict[str, Any]:
        """체결 상세 조회 — 누적 매수/매도 체결량 반환 (FHKST01010200).

        반환:
            buy_vol_total  : 누적 매수체결 수량 (shnu_cntg_smtn)
            sell_vol_total : 누적 매도체결 수량 (seln_cntg_smtn)
            net_buy_count  : 순매수 체결 건수  (ntby_cntg_csnu)
        """
        normalized = self._normalize_symbol(symbol)
        response = self._rest_get(
            "/uapi/domestic-stock/v1/quotations/inquire-ccnl",
            tr_id="FHKST01010200",
            params={
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": normalized,
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized}

        output = (response["body"].get("output") or [{}])[0] if isinstance(
            response["body"].get("output"), list
        ) else (response["body"].get("output") or {})

        return {
            "status": "ok",
            "symbol": normalized,
            "buy_vol_total": self._to_float(output.get("shnu_cntg_smtn")),
            "sell_vol_total": self._to_float(output.get("seln_cntg_smtn")),
            "net_buy_count": self._to_float(output.get("ntby_cntg_csnu")),
            "raw": output,
        }

    def get_order_book(
        self,
        symbol: str,
        *,
        env_dv: str | None = None,
        market_code: str = "J",
    ) -> dict[str, Any]:
        """호가 잔량 조회 — 총 매수/매도 호가 잔량 반환 (FHKST01010900).

        반환:
            bid_qty : 총 매수호가 잔량 (total_bidp_rsqn)
            ask_qty : 총 매도호가 잔량 (total_askp_rsqn)
        """
        normalized = self._normalize_symbol(symbol)
        response = self._rest_get(
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            tr_id="FHKST01010900",
            params={
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": normalized,
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized}

        output = response["body"].get("output1") or response["body"].get("output") or {}

        return {
            "status": "ok",
            "symbol": normalized,
            "bid_qty": self._to_float(output.get("total_bidp_rsqn")),
            "ask_qty": self._to_float(output.get("total_askp_rsqn")),
            "raw": output,
        }

    def venue_capability(self, *, env_dv: str | None = None) -> dict[str, bool]:
        """NXT/SOR support matrix derived from KIS Open API fields and VTS probes.

        Official samples expose:
        - quotes with FID_COND_MRKT_DIV_CODE=J/KRX, NX/NXT, UN/integrated
        - order-cash EXCG_ID_DVSN_CD=KRX/NXT/SOR
        - balance AFHR_FLPR_YN=X for NXT
        - realtime NXT TRs such as H0NXCNT0/H0NXASP0/H0NXMKO0

        VTS accepted SOR at the API layer but direct NXT order returned HTTP 500 in
        an after-hours probe, so demo keeps direct NXT order disabled by default.
        """
        env = self._normalize_env(env_dv)
        return {
            "nxt_quote": True,
            "nxt_realtime_trade": True,
            "nxt_orderbook": True,
            "nxt_order": env == "real",
            "sor_order": True,
            "nxt_fill_query": True,
            "nxt_balance": True,
            "vts_nxt_supported": False,
        }

    def get_nxt_market_context(
        self,
        symbol: str,
        *,
        session: str = "nxt_after",
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        """Return NXT quote context from the KIS quote2 API.

        This is intentionally quote-only. Realtime trade and order-book enrichment
        should be layered in by WebSocket consumers when those streams are active.
        """
        normalized = self._normalize_symbol(symbol)
        response = self._rest_get(
            "/uapi/domestic-stock/v1/quotations/inquire-price-2",
            tr_id="FHPST01010000",
            params={
                "FID_COND_MRKT_DIV_CODE": "NX",
                "FID_INPUT_ISCD": normalized,
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized}
        output = response["body"].get("output") or {}
        return {
            "status": "ok",
            "symbol": normalized,
            "session": session,
            "nxt_price": self._to_float(output.get("stck_prpr")),
            "nxt_volume": self._to_float(output.get("acml_vol")),
            "nxt_turnover": self._to_float(output.get("acml_tr_pbmn")),
            "nxt_vwap": 0.0,
            "nxt_spread": 0.0,
            "nxt_bid_ask_imbalance": 0.0,
            "nxt_trade_count": 0,
            "data_quality": "ok",
            "raw": output,
        }

    # ------------------------------------------------------------------
    # 주문 실행
    # ------------------------------------------------------------------

    @staticmethod
    def get_tick_size(price: int) -> int:
        """KRX 호가단위 반환."""
        if price < 2_000:       return 1
        if price < 5_000:       return 5
        if price < 20_000:      return 10
        if price < 50_000:      return 50
        if price < 200_000:     return 100
        if price < 500_000:     return 500
        return 1_000

    @staticmethod
    def round_to_tick(price: float) -> int:
        """가격을 호가단위로 내림 (매수 시 유리한 방향)."""
        p = int(price)
        tick = KISBrokerAdapter.get_tick_size(p)
        return (p // tick) * tick

    def _parse_account(self) -> tuple[str, str]:
        """account_no 에서 (cano 8자리, acnt_prdt_cd 2자리) 분리.

        지원 형식: "73000000" → ("73000000", product_code or "01")
                   "73000000-01" → ("73000000", "01")
        """
        raw = self.account_no.strip()
        if "-" in raw:
            parts = raw.split("-", 1)
            return parts[0].strip(), parts[1].strip()
        return raw, self.product_code.strip() or "01"

    def place_order_cash(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float = 0.0,
        *,
        order_type: str = "auto",
        excg_id: str = "KRX",
        env_dv: str | None = None,
        dry_run: bool = False,
        ord_dvsn_override: str | None = None,
    ) -> dict[str, Any]:
        """현금 매수/매도 주문 (TTTC0012U / TTTC0011U).

        Args:
            symbol     : 종목코드 6자리 (예: "005930")
            side       : "buy" 또는 "sell"
            qty        : 주문 수량
            price      : 주문 단가. 0 이면 시장가.
            order_type : "limit"=지정가, "market"=시장가, "auto"=price>0 이면 지정가
            excg_id    : "KRX" | "NXT" | "SOR"
            dry_run    : True 이면 API 호출 없이 파라미터만 반환
        """
        if side not in ("buy", "sell"):
            return {"status": "error", "error": f"invalid side: {side}"}
        if qty <= 0:
            return {"status": "error", "error": "qty must be >= 1"}

        env = self._normalize_env(env_dv)
        normalized = self._normalize_symbol(symbol)
        cano, acnt_prdt_cd = self._parse_account()

        # 주문구분 결정
        use_market = (order_type == "market") or (order_type == "auto" and price <= 0)
        if ord_dvsn_override:
            if price <= 0:
                raise ValueError("ord_dvsn_override requires a positive limit price")
            ord_dvsn = ord_dvsn_override
            ord_unpr = str(self.round_to_tick(price))
        else:
            ord_dvsn = "01" if use_market else "00"
            ord_unpr = "0" if use_market else str(self.round_to_tick(price))

        # TR_ID (실전/모의 × 매수/매도)
        tr_map = {
            ("real", "buy"):  "TTTC0012U",
            ("real", "sell"): "TTTC0011U",
            ("demo", "buy"):  "VTTC0012U",
            ("demo", "sell"): "VTTC0011U",
        }
        tr_id = tr_map[(env, side)]

        body = {
            "CANO":             cano,
            "ACNT_PRDT_CD":     acnt_prdt_cd,
            "PDNO":             normalized,
            "ORD_DVSN":         ord_dvsn,
            "ORD_QTY":          str(qty),
            "ORD_UNPR":         ord_unpr,
            "EXCG_ID_DVSN_CD":  excg_id,
            "SLL_TYPE":         "01" if side == "sell" else "",
            "CNDT_PRIC":        "",
        }

        if dry_run:
            return {
                "status": "ok",
                "dry_run": True,
                "symbol": normalized,
                "side": side,
                "qty": qty,
                "ord_dvsn": ord_dvsn,
                "ord_unpr": ord_unpr,
                "tr_id": tr_id,
                "body": body,
            }

        response = self._rest_post(
            "/uapi/domestic-stock/v1/trading/order-cash",
            tr_id=tr_id,
            body=body,
            env_dv=env,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized, "side": side}

        output = response["body"].get("output") or {}
        return {
            "status": "ok",
            "broker": self.name,
            "env_dv": env,
            "symbol": normalized,
            "side": side,
            "qty": qty,
            "ord_dvsn": ord_dvsn,
            "ord_unpr": ord_unpr,
            "order_no": str(output.get("ODNO") or ""),
            "krx_org_no": str(output.get("KRX_FWDG_ORD_ORGNO") or ""),
            "order_time": str(output.get("ORD_TMD") or ""),
            "raw": output,
        }

    def cancel_order(
        self,
        krx_org_no: str,
        order_no: str,
        symbol: str,
        qty: int,
        *,
        cancel_all: bool = True,
        excg_id: str = "KRX",
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        """미체결 주문 취소 (order-rvsecncl, RVSE_CNCL_DVSN_CD=02).

        Args:
            krx_org_no : place_order_cash 반환값의 krx_org_no
            order_no   : place_order_cash 반환값의 order_no
            symbol     : 종목코드
            qty        : 취소 수량 (cancel_all=True 이면 무시)
            cancel_all : True → 잔량 전부 취소
        """
        return self._order_rvsecncl(
            krx_org_no=krx_org_no,
            order_no=order_no,
            symbol=symbol,
            rvse_cncl_dvsn_cd="02",
            ord_dvsn="00",
            qty=qty,
            price=0,
            qty_all=cancel_all,
            excg_id=excg_id,
            env_dv=env_dv,
        )

    def modify_order(
        self,
        krx_org_no: str,
        order_no: str,
        symbol: str,
        qty: int,
        price: float,
        *,
        excg_id: str = "KRX",
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        """미체결 주문 정정 — 단가 변경 (order-rvsecncl, RVSE_CNCL_DVSN_CD=01).

        Args:
            price : 변경할 지정가. 시장가 정정은 불가 (KIS 정책).
        """
        return self._order_rvsecncl(
            krx_org_no=krx_org_no,
            order_no=order_no,
            symbol=symbol,
            rvse_cncl_dvsn_cd="01",
            ord_dvsn="00",
            qty=qty,
            price=price,
            qty_all=False,
            excg_id=excg_id,
            env_dv=env_dv,
        )

    def _order_rvsecncl(
        self,
        *,
        krx_org_no: str,
        order_no: str,
        symbol: str,
        rvse_cncl_dvsn_cd: str,
        ord_dvsn: str,
        qty: int,
        price: float,
        qty_all: bool,
        excg_id: str,
        env_dv: str | None,
    ) -> dict[str, Any]:
        env = self._normalize_env(env_dv)
        normalized = self._normalize_symbol(symbol)
        cano, acnt_prdt_cd = self._parse_account()

        tr_id = "TTTC0013U" if env == "real" else "VTTC0013U"

        body = {
            "CANO":                 cano,
            "ACNT_PRDT_CD":         acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO":  krx_org_no,
            "ORGN_ODNO":            order_no,
            "ORD_DVSN":             ord_dvsn,
            "RVSE_CNCL_DVSN_CD":   rvse_cncl_dvsn_cd,
            "ORD_QTY":              str(qty),
            "ORD_UNPR":             str(self.round_to_tick(price)) if price > 0 else "0",
            "QTY_ALL_ORD_YN":       "Y" if qty_all else "N",
            "EXCG_ID_DVSN_CD":      excg_id,
            "CNDT_PRIC":            "",
        }

        response = self._rest_post(
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            tr_id=tr_id,
            body=body,
            env_dv=env,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized}

        output = response["body"].get("output") or {}
        action = "cancel" if rvse_cncl_dvsn_cd == "02" else "modify"
        return {
            "status": "ok",
            "broker": self.name,
            "env_dv": env,
            "action": action,
            "symbol": normalized,
            "order_no": str(output.get("ODNO") or ""),
            "krx_org_no": str(output.get("KRX_FWDG_ORD_ORGNO") or ""),
            "raw": output,
        }

    def inquire_psbl_order(
        self,
        symbol: str,
        price: float = 0.0,
        *,
        order_type: str = "market",
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        """매수 가능 수량/금액 조회 (TTTC8908R).

        반환:
            max_buy_qty    : 최대 매수 가능 수량 (미수 포함)
            nrcvb_buy_qty  : 미수 없는 매수 가능 수량 (보수적)
            max_buy_amt    : 최대 매수 가능 금액
        """
        env = self._normalize_env(env_dv)
        normalized = self._normalize_symbol(symbol)
        cano, acnt_prdt_cd = self._parse_account()

        tr_id = "TTTC8908R" if env == "real" else "VTTC8908R"
        ord_dvsn = "01" if order_type == "market" or price <= 0 else "00"
        ord_unpr = "0" if ord_dvsn == "01" else str(self.round_to_tick(price))

        response = self._rest_get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            tr_id=tr_id,
            params={
                "CANO":                  cano,
                "ACNT_PRDT_CD":          acnt_prdt_cd,
                "PDNO":                  normalized,
                "ORD_UNPR":              ord_unpr,
                "ORD_DVSN":              ord_dvsn,
                "CMA_EVLU_AMT_ICLD_YN":  "N",
                "OVRS_ICLD_YN":          "N",
            },
            env_dv=env,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized}

        output = response["body"].get("output") or {}
        return {
            "status": "ok",
            "broker": self.name,
            "env_dv": env,
            "symbol": normalized,
            "max_buy_qty": self._to_float(output.get("max_buy_qty")),
            "nrcvb_buy_qty": self._to_float(output.get("nrcvb_buy_qty")),
            "max_buy_amt": self._to_float(output.get("max_buy_amt")),
            "nrcvb_buy_amt": self._to_float(output.get("nrcvb_buy_amt")),
            "raw": output,
        }

    def inquire_balance(
        self,
        *,
        env_dv: str | None = None,
        ctx_fk: str = "",
        ctx_nk: str = "",
    ) -> dict[str, Any]:
        """주식 잔고 조회 (TTTC8434R / VTTC8434R).

        KIS 응답은 output1(보유종목 목록)과 output2(계좌 요약) 두 파트로 구성.
        결과가 100건을 넘으면 ctx_area_fk100/nk100 커서 값으로 페이지를 이어
        호출하면 된다. 이 메서드는 첫 페이지를 반환하고 next_ctx 키에 커서를 담는다.

        반환:
            holdings   : 보유 종목 목록 (list[dict])
              - symbol       : 종목코드
              - name         : 종목명
              - qty          : 보유수량
              - tradable_qty : 매도가능수량
              - avg_price    : 평균단가
              - current_price: 현재가
              - eval_amount  : 평가금액
              - profit_loss  : 평가손익
              - profit_rate  : 수익률 (%)
            summary    : 계좌 요약 (dict)
              - deposit      : 예수금총금액
              - total_eval   : 총평가금액 (예수금 + 평가금액)
              - purchase_amt : 매입금액합계
              - eval_amt     : 평가금액합계
              - profit_loss  : 평가손익합계
              - profit_rate  : 수익률합계 (%)
            next_ctx   : 다음 페이지 커서 {"fk": ..., "nk": ...} or None
        """
        env = self._normalize_env(env_dv)
        cano, acnt_prdt_cd = self._parse_account()
        tr_id = "TTTC8434R" if env == "real" else "VTTC8434R"

        response = self._rest_get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id=tr_id,
            params={
                "CANO":                   cano,
                "ACNT_PRDT_CD":           acnt_prdt_cd,
                "AFHR_FLPR_YN":           "N",
                "OFL_YN":                 "",
                "INQR_DVSN":              "01",
                "UNPR_DVSN":              "01",
                "FUND_STTL_ICLD_YN":      "N",
                "FNCG_AMT_AUTO_RDPT_YN":  "N",
                "PRCS_DVSN":              "00",
                "CTX_AREA_FK100":         ctx_fk,
                "CTX_AREA_NK100":         ctx_nk,
            },
            env_dv=env,
        )
        if response["status"] != "ok":
            return response

        body = response["body"]
        output1: list[dict[str, Any]] = body.get("output1") or []
        output2_raw = body.get("output2") or {}
        if isinstance(output2_raw, list):
            output2: dict[str, Any] = output2_raw[0] if output2_raw else {}
        else:
            output2 = output2_raw

        holdings = [
            {
                "symbol":        str(row.get("pdno") or ""),
                "name":          str(row.get("prdt_name") or ""),
                "qty":           self._to_float(row.get("hldg_qty")),
                "tradable_qty":  self._to_float(row.get("ord_psbl_qty")),
                "avg_price":     self._to_float(row.get("pchs_avg_pric")),
                "current_price": self._to_float(row.get("prpr")),
                "eval_amount":   self._to_float(row.get("evlu_amt")),
                "profit_loss":   self._to_float(row.get("evlu_pfls_amt")),
                "profit_rate":   self._to_float(row.get("evlu_pfls_rt")),
            }
            for row in output1
            if self._to_float(row.get("hldg_qty")) > 0
        ]

        summary = {
            "deposit":      self._to_float(output2.get("dnca_tot_amt")),
            "total_eval":   self._to_float(output2.get("tot_evlu_amt")),
            "purchase_amt": self._to_float(output2.get("pchs_amt_smtl_amt")),
            "eval_amt":     self._to_float(output2.get("evlu_amt_smtl_amt")),
            "profit_loss":  self._to_float(output2.get("evlu_pfls_smtl_amt")),
            "profit_rate":  self._to_float(output2.get("prft_rate")),
        }

        nxt_fk = str(body.get("ctx_area_fk100") or "").strip()
        nxt_nk = str(body.get("ctx_area_nk100") or "").strip()
        next_ctx = {"fk": nxt_fk, "nk": nxt_nk} if nxt_fk or nxt_nk else None

        return {
            "status":   "ok",
            "broker":   self.name,
            "env_dv":   env,
            "holdings": holdings,
            "summary":  summary,
            "next_ctx": next_ctx,
        }

    # ------------------------------------------------------------------
    # REST helpers
    # ------------------------------------------------------------------

    def _rest_post(
        self,
        path: str,
        *,
        tr_id: str,
        body: dict[str, Any],
        env_dv: str | None,
    ) -> dict[str, Any]:
        env = self._normalize_env(env_dv)
        auth = self.issue_access_token(env_dv=env)
        if auth["status"] != "ok":
            return {
                "status": "error",
                "env_dv": env,
                "error": "KIS access token issuance failed",
                "auth": auth,
            }

        url = f"{self._base_url_for_env(env)}{path}"
        app_key, app_secret = self._credentials_for_env(env)
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "charset": "UTF-8",
            "authorization": f"Bearer {auth['access_token']}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": tr_id,
        }

        try:
            response = self.session.post(url, headers=headers, json=body, timeout=self.timeout)
            response.raise_for_status()
            resp_body = response.json()
        except requests.RequestException as exc:
            resp_body = None
            status_code = None
            response = getattr(exc, "response", None)
            if response is not None:
                status_code = response.status_code
                try:
                    resp_body = response.json()
                except ValueError:
                    resp_body = {"raw_text": response.text[:500]}
            return {
                "status": "error",
                "env_dv": env,
                "error": str(exc),
                "url": url,
                "status_code": status_code,
                "body": resp_body,
            }
        except ValueError as exc:
            return {"status": "error", "env_dv": env, "error": f"invalid response: {exc}", "url": url}

        if str(resp_body.get("rt_cd", "0")) not in {"0", ""}:
            return {
                "status": "error",
                "env_dv": env,
                "error": resp_body.get("msg1") or resp_body.get("msg_cd") or "KIS API error",
                "url": url,
                "body": resp_body,
            }
        return {"status": "ok", "env_dv": env, "url": url, "body": resp_body}

    def get_volume_ranking(
        self,
        market: str = "J",
        top_n: int = 30,
        *,
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        """거래량 순위 조회 (FHPST01710000).

        Args:
            market : "J" = 코스피, "Q" = 코스닥, "0" = 전체
            top_n  : 상위 N종목 반환

        반환:
            items : list[dict] — symbol, name, price, change_rate,
                                 trading_value, volume, exec_strength
        """
        response = self._rest_get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            tr_id="FHPST01710000",
            params={
                "FID_COND_MRKT_DIV_CODE": market,
                "FID_COND_SCR_DIV_CODE":  "20171",
                "FID_INPUT_ISCD":         "0000",
                "FID_DIV_CLS_CODE":       "0",          # 0=전체, 1=보통주, 2=우선주
                "FID_BLNG_CLS_CODE":      "0",          # 0=평균거래량
                "FID_TRGT_CLS_CODE":      "111111111",  # 9자리: 증거금 30~100%, 신용보증금 30~60%
                "FID_TRGT_EXLS_CLS_CODE": "0000000000", # 10자리 제외 조건 (전부 미제외)
                "FID_INPUT_PRICE_1":      "",
                "FID_INPUT_PRICE_2":      "",
                "FID_VOL_CNT":            "",
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "items": []}

        rows = response["body"].get("output") or []
        items = []
        for row in rows[:top_n]:
            items.append({
                "symbol":        str(row.get("mksc_shrn_iscd") or ""),
                "name":          str(row.get("hts_kor_isnm") or ""),
                "price":         self._to_float(row.get("stck_prpr")),
                "change_rate":   self._to_float(row.get("prdy_ctrt")) / 100.0,
                "trading_value": self._to_float(row.get("acml_tr_pbmn")),
                "volume":        self._to_float(row.get("acml_vol")),
                "exec_strength": self._to_float(row.get("ntby_cntg_csnu")),  # 순매수체결건수 근사
            })
        return {"status": "ok", "items": items}

    def get_intraday_bars(
        self,
        symbol: str,
        interval: str,
        start: str,
        end: str,
        *,
        env_dv: str | None = None,
        market_code: str = "J",
        include_past_data: bool = True,
    ) -> dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_interval = self._normalize_interval(interval)
        response = self._rest_get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            tr_id="FHKST03010200",
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": normalized_symbol,
                "FID_INPUT_HOUR_1": self._normalize_end_time(end),
                "FID_PW_DATA_INCU_YN": "Y" if include_past_data else "N",
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized_symbol, "interval": normalized_interval}

        body = response["body"]
        header = body.get("output1") or {}
        rows = body.get("output2") or []
        normalized_rows = [bar for bar in (self._normalize_bar_row(header, row) for row in rows) if bar]
        normalized_rows.sort(key=lambda row: row["timestamp"])
        filtered_rows = self._filter_intraday_rows(normalized_rows, start=start, end=end)
        aggregated_rows = self._aggregate_bars(filtered_rows, normalized_interval)
        return {
            "status": "ok",
            "broker": self.name,
            "env_dv": response["env_dv"],
            "symbol": normalized_symbol,
            "market_code": market_code,
            "interval": normalized_interval,
            "bars": aggregated_rows,
            "raw_header": header,
            "raw_count": len(rows),
        }

    def place_order(
        self,
        order: BrokerOrderRequest,
        *,
        mode: str,
        dry_run: bool,
    ) -> BrokerExecutionResult:
        if mode == "live" and not self.supports_live:
            return BrokerExecutionResult(
                broker=self.name,
                mode=mode,
                status="error",
                symbol=order.symbol,
                side=order.side,
                message="KIS live execution not enabled in scaffold.",
                accepted=False,
                dry_run=dry_run,
                raw={"order": order.metadata},
            )
        return BrokerExecutionResult(
            broker=self.name,
            mode=mode,
            status="accepted",
            order_id=f"kis-{mode}-{order.symbol}",
            symbol=order.symbol,
            side=order.side,
            message="KIS order simulated by scaffold adapter.",
            accepted=True,
            dry_run=dry_run,
            raw={
                "base_url": self.base_url,
                "account_no": self.account_no[-4:] if self.account_no else "",
                "product_code": self.product_code,
                "qty_policy": order.qty_policy,
                "limit_policy": order.limit_policy,
            },
        )

    def _rest_get(
        self,
        path: str,
        *,
        tr_id: str,
        params: dict[str, Any],
        env_dv: str | None,
        _retries: int = 2,
    ) -> dict[str, Any]:
        import time as _time
        env = self._normalize_env(env_dv)
        auth = self.issue_access_token(env_dv=env)
        if auth["status"] != "ok":
            return {
                "status": "error",
                "env_dv": env,
                "error": "KIS access token issuance failed",
                "auth": auth,
            }

        url = f"{self._base_url_for_env(env)}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "charset": "UTF-8",
            "authorization": f"Bearer {auth['access_token']}",
            "appkey": self._credentials_for_env(env)[0],
            "appsecret": self._credentials_for_env(env)[1],
            "tr_id": tr_id,
        }
        last_exc: str = ""
        for attempt in range(1 + _retries):
            try:
                response = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
                if response.status_code == 500 and attempt < _retries:
                    _time.sleep(1.0)
                    continue
                response.raise_for_status()
                body = response.json()
                break
            except requests.RequestException as exc:
                last_exc = str(exc)
                if attempt < _retries:
                    _time.sleep(1.0)
                    continue
                return {"status": "error", "env_dv": env, "error": last_exc, "url": url, "params": params}
            except ValueError as exc:
                return {"status": "error", "env_dv": env,
                        "error": f"invalid KIS response: {exc}", "url": url, "params": params}

        if str(body.get("rt_cd", "0")) not in {"0", ""}:
            return {
                "status": "error",
                "env_dv": env,
                "error": body.get("msg1") or body.get("msg_cd") or "KIS API returned error",
                "url": url,
                "params": params,
                "body": body,
            }
        return {"status": "ok", "env_dv": env, "url": url, "params": params, "body": body}

    def _credentials_for_env(self, env_dv: str) -> tuple[str, str]:
        env = self._normalize_env(env_dv)
        if env == "demo":
            return self.paper_app_key, self.paper_app_secret
        return self.app_key, self.app_secret

    def _base_url_for_env(self, env_dv: str) -> str:
        env = self._normalize_env(env_dv)
        return self.paper_base_url if env == "demo" else self.base_url

    def _normalize_env(self, env_dv: str | None) -> str:
        normalized = str(env_dv or self.default_env or "real").strip().lower()
        if normalized in {"vps", "paper"}:
            return "demo"
        if normalized in {"prod", "live"}:
            return "real"
        if normalized not in {"real", "demo"}:
            return "real"
        return normalized

    def _token_is_valid(self, state: _TokenState) -> bool:
        if not state.access_token or not state.expires_at:
            return False
        return state.expires_at > (self._now_kst() + timedelta(seconds=60))

    def _parse_token_expiry(self, payload: dict[str, Any]) -> datetime | None:
        raw = payload.get("access_token_token_expired") or payload.get("access_token_expired")
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S"):
            try:
                return datetime.strptime(str(raw), fmt)
            except ValueError:
                continue
        return None

    def _normalize_symbol(self, symbol: str) -> str:
        text = str(symbol or "").strip().upper()
        if not text:
            return ""
        if "." in text:
            text = text.split(".", 1)[0]
        if text.startswith("Q") and len(text) == 7:
            return text
        return text

    def _normalize_interval(self, interval: str) -> str:
        text = str(interval or "1m").strip().lower()
        if text == "60m":
            return "1h"
        return text

    def _normalize_end_time(self, end: str) -> str:
        text = str(end or "").strip()
        if not text:
            return "153000"
        if len(text) == 6 and text.isdigit():
            return text
        if "T" in text:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().strftime("%H%M%S")
            except ValueError:
                return "153000"
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            return digits[-6:]
        return "153000"

    def _normalize_bar_row(self, header: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
        date_text = (
            str(row.get("stck_bsop_date") or row.get("bsop_date") or header.get("stck_bsop_date") or "")
            .strip()
        )
        time_text = str(row.get("stck_cntg_hour") or row.get("cntg_hour") or "").strip()
        if not date_text or not time_text:
            return None
        timestamp = self._combine_trade_timestamp(date_text, time_text)
        if timestamp is None:
            return None
        return {
            "timestamp": timestamp,
            "open": self._to_float(row.get("stck_oprc")),
            "high": self._to_float(row.get("stck_hgpr")),
            "low": self._to_float(row.get("stck_lwpr")),
            "close": self._to_float(row.get("stck_prpr")),
            "volume": self._to_float(row.get("cntg_vol")),
            "raw": row,
        }

    def _combine_trade_timestamp(self, date_text: str, time_text: str) -> str | None:
        digits_date = "".join(ch for ch in str(date_text) if ch.isdigit())
        digits_time = "".join(ch for ch in str(time_text) if ch.isdigit())
        if len(digits_date) != 8 or len(digits_time) < 6:
            return None
        try:
            dt = datetime.strptime(f"{digits_date}{digits_time[:6]}", "%Y%m%d%H%M%S")
        except ValueError:
            return None
        return dt.isoformat()

    def _filter_intraday_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        start_marker = self._normalize_time_filter(start)
        end_marker = self._normalize_time_filter(end)
        filtered: list[dict[str, Any]] = []
        for row in rows:
            timestamp = row["timestamp"]
            time_fragment = timestamp[11:19]
            if start_marker and time_fragment < start_marker:
                continue
            if end_marker and time_fragment > end_marker:
                continue
            filtered.append(row)
        return filtered

    def _normalize_time_filter(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "T" in text:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%H:%M:%S")
            except ValueError:
                return ""
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            return f"{digits[-6:-4]}:{digits[-4:-2]}:{digits[-2:]}"
        return ""

    def _aggregate_bars(self, rows: list[dict[str, Any]], interval: str) -> list[dict[str, Any]]:
        step = self._interval_minutes(interval)
        if step == 1:
            return [{k: v for k, v in row.items() if k != "raw"} for row in rows]

        buckets: dict[datetime, list[dict[str, Any]]] = {}
        for row in rows:
            dt = datetime.fromisoformat(row["timestamp"])
            minute = (dt.minute // step) * step
            bucket_dt = dt.replace(minute=minute, second=0, microsecond=0)
            buckets.setdefault(bucket_dt, []).append(row)

        aggregated: list[dict[str, Any]] = []
        for bucket_dt in sorted(buckets):
            group = buckets[bucket_dt]
            aggregated.append(
                {
                    "timestamp": bucket_dt.isoformat(),
                    "open": group[0]["open"],
                    "high": max(self._to_float(item["high"]) for item in group),
                    "low": min(self._to_float(item["low"]) for item in group),
                    "close": group[-1]["close"],
                    "volume": sum(self._to_float(item["volume"]) for item in group),
                }
            )
        return aggregated

    def _interval_minutes(self, interval: str) -> int:
        mapping = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
        return mapping.get(interval, 1)

    def _to_float(self, value: Any) -> float:
        if value in (None, "", "-"):
            return 0.0
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    def _now_kst(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None) + KST
