"""Kiwoom broker adapter with token, quote, order, and websocket support."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from src.brokers.base import BrokerAdapter, BrokerExecutionResult, BrokerOrderRequest


PROD_BASE_URL = "https://api.kiwoom.com"
DEMO_BASE_URL = "https://mockapi.kiwoom.com"
DEFAULT_WEBSOCKET_URL = "wss://api.kiwoom.com:10000/api/dostk/websocket"
KST = timedelta(hours=9)


@dataclass
class _TokenState:
    access_token: str = ""
    expires_at: datetime | None = None


class KiwoomBrokerAdapter(BrokerAdapter):
    name = "kiwoom"
    supports_live = True
    supports_paper = True

    def __init__(
        self,
        *,
        app_key: str = "",
        secret_key: str = "",
        account_no: str = "",
        base_url: str = "",
        websocket_url: str = "",
        paper_app_key: str = "",
        paper_secret_key: str = "",
        paper_base_url: str = "",
        default_env: str = "real",
        session: requests.Session | None = None,
        websocket_factory: Any | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.app_key = app_key
        self.secret_key = secret_key
        self.account_no = account_no
        self.base_url = base_url or PROD_BASE_URL
        self.websocket_url = websocket_url or DEFAULT_WEBSOCKET_URL
        self.paper_app_key = paper_app_key
        self.paper_secret_key = paper_secret_key
        self.paper_base_url = paper_base_url or DEMO_BASE_URL
        self.default_env = self._normalize_env(default_env)
        self.session = session or requests.Session()
        self.websocket_factory = websocket_factory
        self.timeout = timeout
        self._tokens: dict[str, _TokenState] = {"real": _TokenState(), "demo": _TokenState()}

    @classmethod
    def from_env(cls) -> "KiwoomBrokerAdapter":
        return cls(
            app_key=os.getenv("KIWOOM_APP_KEY", ""),
            secret_key=os.getenv("KIWOOM_SECRET_KEY", ""),
            account_no=os.getenv("KIWOOM_ACCOUNT_NO", ""),
            base_url=os.getenv("KIWOOM_BASE_URL", ""),
            websocket_url=os.getenv("KIWOOM_WS_URL", ""),
            paper_app_key=os.getenv("KIWOOM_PAPER_APP_KEY", ""),
            paper_secret_key=os.getenv("KIWOOM_PAPER_SECRET_KEY", ""),
            paper_base_url=os.getenv("KIWOOM_PAPER_BASE_URL", ""),
            default_env=os.getenv("KIWOOM_ENV", "real"),
        )

    def check_connection(self) -> dict[str, Any]:
        missing = [
            key
            for key, value in {
                "KIWOOM_APP_KEY": self.app_key,
                "KIWOOM_SECRET_KEY": self.secret_key,
                "KIWOOM_ACCOUNT_NO": self.account_no,
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
            "paper_credentials_ready": bool(self.paper_app_key and self.paper_secret_key),
            "base_url": self.base_url,
            "paper_base_url": self.paper_base_url,
            "websocket_url": self.websocket_url,
            "message": (
                "Kiwoom adapter ready for OAuth, REST quote/chart/order, and websocket helpers."
            ),
        }

    def issue_access_token(self, *, env_dv: str | None = None, force: bool = False) -> dict[str, Any]:
        env = self._normalize_env(env_dv)
        state = self._tokens[env]
        if not force and self._token_is_valid(state):
            return {
                "status": "ok",
                "env_dv": env,
                "cached": True,
                "access_token": state.access_token,
                "expires_at": state.expires_at.isoformat() if state.expires_at else "",
            }

        app_key, secret_key = self._credentials_for_env(env)
        if not app_key or not secret_key:
            return {
                "status": "error",
                "env_dv": env,
                "error": f"missing Kiwoom credentials for env '{env}'",
                "required_env": (
                    ["KIWOOM_APP_KEY", "KIWOOM_SECRET_KEY"]
                    if env == "real"
                    else ["KIWOOM_PAPER_APP_KEY", "KIWOOM_PAPER_SECRET_KEY"]
                ),
            }

        url = f"{self._base_url_for_env(env)}/oauth2/token"
        payload = {"grant_type": "client_credentials", "appkey": app_key, "secretkey": secret_key}
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        try:
            response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            return {"status": "error", "env_dv": env, "error": str(exc), "url": url}
        except ValueError as exc:
            return {"status": "error", "env_dv": env, "error": f"invalid token response: {exc}", "url": url}

        token = str(body.get("token") or "").strip()
        if not token:
            return {"status": "error", "env_dv": env, "error": "token missing from Kiwoom response", "raw": body}

        expires_at = self._parse_token_expiry(body) or (self._now_kst() + timedelta(hours=23))
        self._tokens[env] = _TokenState(token, expires_at)
        return {
            "status": "ok",
            "env_dv": env,
            "cached": False,
            "access_token": token,
            "expires_at": expires_at.isoformat(),
            "raw": body,
        }

    def get_quote(self, symbol: str, market_code: str = "KRX", *, env_dv: str | None = None) -> dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol, market_code=market_code)
        response = self._rest_post(
            "/api/dostk/mrkcond",
            api_id="ka10007",
            body={"stk_cd": normalized_symbol},
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized_symbol}

        payload = response["body"]
        data = self._unwrap_single_record(payload)
        return {
            "status": "ok",
            "broker": self.name,
            "env_dv": response["env_dv"],
            "symbol": normalized_symbol,
            "market_code": market_code,
            "quote": {
                "last": self._to_float(self._pick(data, "cur_prc", "close_pric", "last_pric")),
                "open": self._to_float(self._pick(data, "open_pric", "stt_pric")),
                "high": self._to_float(self._pick(data, "high_pric", "high")),
                "low": self._to_float(self._pick(data, "low_pric", "low")),
                "volume": self._to_float(self._pick(data, "trde_qty", "acc_trde_qty")),
                "turnover": self._to_float(self._pick(data, "acc_trde_prica", "trde_prica")),
                "change": self._to_float(self._pick(data, "pred_pre", "pred_pre_pric")),
                "change_rate": self._to_float(self._pick(data, "flu_rt", "pred_pre_rt")),
                "timestamp": str(self._pick(data, "tm", "trde_tm", "bid_req_base_tm") or ""),
            },
            "raw": data,
        }

    def get_intraday_bars(
        self,
        symbol: str,
        interval: str,
        start: str,
        end: str,
        *,
        env_dv: str | None = None,
        market_code: str = "KRX",
    ) -> dict[str, Any]:
        normalized_interval = self._normalize_interval(interval)
        normalized_symbol = self._normalize_symbol(symbol, market_code=market_code)
        today = self._today_kst().strftime("%Y%m%d")
        # Kiwoom chart docs use /api/dostk/chart for chart TRs; ka10006 is the minute-bar request.
        response = self._rest_post(
            "/api/dostk/chart",
            api_id="ka10006",
            body={
                "stk_cd": normalized_symbol,
                "tic_scope": str(self._interval_minutes(normalized_interval)),
                "upd_stkpc_tp": "1",
                "dt": today,
            },
            env_dv=env_dv,
        )
        if response["status"] != "ok":
            return {**response, "symbol": normalized_symbol, "interval": normalized_interval}

        payload = response["body"]
        rows = self._find_first_list_of_dicts(payload)
        normalized_rows = [bar for bar in (self._normalize_bar_row(row) for row in rows) if bar]
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
                message="Kiwoom live execution not enabled in scaffold.",
                accepted=False,
                dry_run=dry_run,
                raw={"order": order.metadata},
            )
        if mode != "live" or dry_run:
            return BrokerExecutionResult(
                broker=self.name,
                mode=mode,
                status="accepted",
                order_id=f"kiwoom-{mode}-{order.symbol}",
                symbol=order.symbol,
                side=order.side,
                message="Kiwoom order simulated by adapter.",
                accepted=True,
                dry_run=dry_run,
                raw={
                    "base_url": self.base_url,
                    "account_no": self.account_no[-4:] if self.account_no else "",
                    "qty_policy": order.qty_policy,
                    "limit_policy": order.limit_policy,
                    "quantity": order.quantity,
                    "limit_price": order.limit_price,
                },
            )
        if order.quantity is None or order.quantity <= 0:
            return BrokerExecutionResult(
                broker=self.name,
                mode=mode,
                status="error",
                symbol=order.symbol,
                side=order.side,
                message="Kiwoom live order requires explicit positive quantity.",
                accepted=False,
                dry_run=dry_run,
                raw={"order": order.metadata},
            )
        side = str(order.side or "").strip().upper()
        api_id = self._order_api_id(side)
        if not api_id:
            return BrokerExecutionResult(
                broker=self.name,
                mode=mode,
                status="error",
                symbol=order.symbol,
                side=order.side,
                message=f"Unsupported Kiwoom side: {order.side}",
                accepted=False,
                dry_run=dry_run,
                raw={"order": order.metadata},
            )
        market_code = self._normalize_exchange(str(order.metadata.get("market_code") or "KRX"))
        symbol = self._normalize_symbol(order.symbol, market_code=market_code)
        trade_type = self._map_trade_type(order.limit_policy, order.limit_price)
        payload = {
            "dmst_stex_tp": market_code,
            "stk_cd": symbol,
            "ord_qty": self._to_int_string(order.quantity),
            "ord_uv": self._to_price_string(order.limit_price, trade_type),
            "trde_tp": trade_type,
            "cond_uv": self._to_price_string(order.metadata.get("conditional_price")),
        }
        response = self._rest_post("/api/dostk/ordr", api_id=api_id, body=payload, env_dv="real")
        if response["status"] != "ok":
            return BrokerExecutionResult(
                broker=self.name,
                mode=mode,
                status="error",
                symbol=symbol,
                side=side,
                message=response.get("error") or "Kiwoom order request failed",
                accepted=False,
                dry_run=dry_run,
                raw=response,
            )
        body = response["body"]
        return BrokerExecutionResult(
            broker=self.name,
            mode=mode,
            status="accepted",
            order_id=str(body.get("ord_no") or ""),
            symbol=symbol,
            side=side,
            message="Kiwoom live order accepted.",
            accepted=True,
            dry_run=dry_run,
            raw={
                "request": payload,
                "response": body,
            },
        )

    def modify_order(
        self,
        order_id: str,
        *,
        symbol: str,
        quantity: float | None = None,
        limit_price: float | None = None,
        market_code: str = "KRX",
        limit_policy: str = "",
        conditional_price: float | None = None,
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        trade_type = self._map_trade_type(limit_policy, limit_price)
        payload = {
            "orgn_ord_no": str(order_id),
            "dmst_stex_tp": self._normalize_exchange(market_code),
            "stk_cd": self._normalize_symbol(symbol, market_code=market_code),
            "ord_qty": self._to_int_string(quantity),
            "ord_uv": self._to_price_string(limit_price, trade_type),
            "trde_tp": trade_type,
            "cond_uv": self._to_price_string(conditional_price),
        }
        response = self._rest_post("/api/dostk/ordr", api_id="kt10002", body=payload, env_dv=env_dv or "real")
        if response["status"] != "ok":
            return response
        body = response["body"]
        return {
            "status": "ok",
            "broker": self.name,
            "action": "modify_order",
            "order_id": str(body.get("ord_no") or order_id),
            "request": payload,
            "response": body,
        }

    def cancel_order(
        self,
        order_id: str,
        *,
        symbol: str = "",
        quantity: float | None = None,
        market_code: str = "KRX",
        env_dv: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "orgn_ord_no": str(order_id),
            "dmst_stex_tp": self._normalize_exchange(market_code),
            "stk_cd": self._normalize_symbol(symbol, market_code=market_code) if symbol else "",
            "ord_qty": self._to_int_string(quantity),
        }
        response = self._rest_post("/api/dostk/ordr", api_id="kt10003", body=payload, env_dv=env_dv or "real")
        if response["status"] != "ok":
            return response
        body = response["body"]
        return {
            "status": "ok",
            "broker": self.name,
            "action": "cancel_order",
            "order_id": str(body.get("ord_no") or order_id),
            "request": payload,
            "response": body,
        }

    def get_orders(
        self,
        *,
        env_dv: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._rest_post(
            "/api/dostk/acnt",
            api_id="kt00008",
            body=self._normalize_account_filters(filters),
            env_dv=env_dv or "real",
        )
        if response["status"] != "ok":
            return response
        rows = self._find_first_list_of_dicts(response["body"])
        return {
            "status": "ok",
            "broker": self.name,
            "action": "get_orders",
            "orders": rows,
            "raw": response["body"],
        }

    def get_fills(
        self,
        *,
        env_dv: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._rest_post(
            "/api/dostk/acnt",
            api_id="kt00008",
            body=self._normalize_account_filters(filters),
            env_dv=env_dv or "real",
        )
        if response["status"] != "ok":
            return response
        rows = self._find_first_list_of_dicts(response["body"])
        fills = [row for row in rows if self._row_looks_filled(row)]
        return {
            "status": "ok",
            "broker": self.name,
            "action": "get_fills",
            "fills": fills,
            "raw": response["body"],
        }

    def build_quote_subscription(
        self,
        symbols: list[str],
        *,
        quote_types: list[str] | None = None,
        grp_no: str = "1",
        refresh: str = "1",
        market_code: str = "KRX",
    ) -> dict[str, Any]:
        return {
            "trnm": "REG",
            "grp_no": str(grp_no),
            "refresh": str(refresh),
            "data": [
                {
                    "item": [self._normalize_symbol(symbol, market_code=market_code) for symbol in symbols],
                    "type": quote_types or ["0B"],
                }
            ],
        }

    def build_condition_list_request(self) -> dict[str, Any]:
        return {"trnm": "CNSRLST"}

    def build_condition_search_request(self, seq: str, *, realtime: bool = False) -> dict[str, Any]:
        return {"trnm": "CNSRREQ", "seq": str(seq), "search_tp": "1" if realtime else "0"}

    def build_condition_release_request(self, seq: str) -> dict[str, Any]:
        return {"trnm": "CNSRCLR", "seq": str(seq)}

    async def websocket_roundtrip(
        self,
        requests_payload: list[dict[str, Any]],
        *,
        env_dv: str | None = None,
        receive_count: int = 1,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        env = self._normalize_env(env_dv)
        auth = self.issue_access_token(env_dv=env)
        if auth["status"] != "ok":
            return {"status": "error", "error": "Kiwoom websocket login token unavailable", "auth": auth}

        connect = self.websocket_factory or self._load_websocket_connect()
        uri = self._websocket_url_for_env(env)
        messages: list[dict[str, Any]] = []
        async with connect(uri) as ws:
            await ws.send(json.dumps({"trnm": "LOGIN", "token": auth["access_token"]}, ensure_ascii=False))
            login_reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            messages.append(login_reply)
            for payload in requests_payload:
                await ws.send(json.dumps(payload, ensure_ascii=False))
            for _ in range(max(receive_count, 0)):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except TimeoutError:
                    break
                messages.append(json.loads(raw))
        return {"status": "ok", "broker": self.name, "uri": uri, "messages": messages}

    def run_websocket_roundtrip(
        self,
        requests_payload: list[dict[str, Any]],
        *,
        env_dv: str | None = None,
        receive_count: int = 1,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.websocket_roundtrip(
                    requests_payload,
                    env_dv=env_dv,
                    receive_count=receive_count,
                    timeout=timeout,
                )
            )
        return {"status": "error", "error": "run_websocket_roundtrip cannot be used inside an active event loop"}

    def list_conditions(self, *, env_dv: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
        response = self.run_websocket_roundtrip([self.build_condition_list_request()], env_dv=env_dv, receive_count=1, timeout=timeout)
        if response["status"] != "ok":
            return response
        last = response["messages"][-1] if response["messages"] else {}
        data = last.get("data") or []
        conditions = [{"seq": str(item[0]), "name": str(item[1])} for item in data if isinstance(item, (list, tuple)) and len(item) >= 2]
        return {"status": "ok", "broker": self.name, "conditions": conditions, "raw": response}

    def run_condition_search(
        self,
        seq: str,
        *,
        realtime: bool = False,
        env_dv: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        response = self.run_websocket_roundtrip(
            [self.build_condition_search_request(seq, realtime=realtime)],
            env_dv=env_dv,
            receive_count=1,
            timeout=timeout,
        )
        if response["status"] != "ok":
            return response
        last = response["messages"][-1] if response["messages"] else {}
        return {"status": "ok", "broker": self.name, "seq": str(seq), "realtime": realtime, "result": last, "raw": response}

    def release_condition_search(self, seq: str, *, env_dv: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
        response = self.run_websocket_roundtrip(
            [self.build_condition_release_request(seq)],
            env_dv=env_dv,
            receive_count=1,
            timeout=timeout,
        )
        if response["status"] != "ok":
            return response
        last = response["messages"][-1] if response["messages"] else {}
        return {"status": "ok", "broker": self.name, "seq": str(seq), "result": last, "raw": response}

    def _rest_post(
        self,
        path: str,
        *,
        api_id: str,
        body: dict[str, Any],
        env_dv: str | None,
        cont_yn: str = "N",
        next_key: str = "",
    ) -> dict[str, Any]:
        env = self._normalize_env(env_dv)
        auth = self.issue_access_token(env_dv=env)
        if auth["status"] != "ok":
            return {"status": "error", "env_dv": env, "error": "Kiwoom access token issuance failed", "auth": auth}

        url = f"{self._base_url_for_env(env)}{path}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {auth['access_token']}",
            "api-id": api_id,
            "cont-yn": cont_yn,
            "next-key": next_key,
        }
        try:
            response = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return {"status": "error", "env_dv": env, "error": str(exc), "url": url, "body": body}
        except ValueError as exc:
            return {"status": "error", "env_dv": env, "error": f"invalid Kiwoom response: {exc}", "url": url, "body": body}

        if int(payload.get("return_code", 0)) != 0:
            return {
                "status": "error",
                "env_dv": env,
                "error": payload.get("return_msg") or "Kiwoom API returned error",
                "url": url,
                "body": body,
                "payload": payload,
            }
        return {"status": "ok", "env_dv": env, "url": url, "body": payload}

    def _credentials_for_env(self, env_dv: str) -> tuple[str, str]:
        env = self._normalize_env(env_dv)
        if env == "demo":
            return self.paper_app_key, self.paper_secret_key
        return self.app_key, self.secret_key

    def _base_url_for_env(self, env_dv: str) -> str:
        env = self._normalize_env(env_dv)
        return self.paper_base_url if env == "demo" else self.base_url

    def _websocket_url_for_env(self, env_dv: str) -> str:
        env = self._normalize_env(env_dv)
        if env == "demo":
            return self.websocket_url.replace("wss://api.kiwoom.com:10000", "wss://mockapi.kiwoom.com:10000")
        return self.websocket_url

    def _normalize_env(self, env_dv: str | None) -> str:
        normalized = str(env_dv or self.default_env or "real").strip().lower()
        if normalized in {"mock", "paper"}:
            return "demo"
        if normalized in {"prod", "live"}:
            return "real"
        if normalized not in {"real", "demo"}:
            return "real"
        return normalized

    def _token_is_valid(self, state: _TokenState) -> bool:
        return bool(state.access_token and state.expires_at and state.expires_at > (self._now_kst() + timedelta(seconds=60)))

    def _parse_token_expiry(self, payload: dict[str, Any]) -> datetime | None:
        raw = payload.get("expires_dt")
        if not raw:
            return None
        for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(raw), fmt)
            except ValueError:
                continue
        return None

    def _normalize_symbol(self, symbol: str, *, market_code: str = "KRX") -> str:
        text = str(symbol or "").strip().upper()
        if "." in text:
            base, suffix = text.split(".", 1)
            if suffix == "KQ":
                return f"{base}_KQ"
            return base
        if "_" in text:
            return text
        if market_code.upper() == "NXT":
            return f"{text}_NX"
        if market_code.upper() == "SOR":
            return f"{text}_AL"
        return text

    def _normalize_exchange(self, market_code: str) -> str:
        normalized = str(market_code or "KRX").strip().upper()
        if normalized in {"KRX", "NXT", "SOR"}:
            return normalized
        return "KRX"

    def _order_api_id(self, side: str) -> str:
        if side == "BUY":
            return "kt10000"
        if side in {"SELL", "REDUCE"}:
            return "kt10001"
        return ""

    def _map_trade_type(self, limit_policy: str, limit_price: float | None) -> str:
        normalized = str(limit_policy or "").strip().lower()
        mapping = {
            "market": "3",
            "market_order": "3",
            "marketable_limit": "6",
            "best_limit": "6",
            "most_favorable": "6",
            "top_priority": "7",
            "best_bid_offer": "7",
            "limit_ioc": "10",
            "market_ioc": "13",
            "best_ioc": "16",
            "limit_fok": "20",
            "market_fok": "23",
            "best_fok": "26",
        }
        if normalized in mapping:
            return mapping[normalized]
        if limit_price is None:
            return "3"
        return "0"

    def _to_int_string(self, value: Any) -> str:
        if value in (None, "", 0):
            return "0"
        return str(int(round(float(value))))

    def _to_price_string(self, value: Any, trade_type: str | None = None) -> str:
        if trade_type == "3":
            return ""
        if value in (None, "", 0):
            return ""
        return str(int(round(float(value))))

    def _normalize_interval(self, interval: str) -> str:
        text = str(interval or "1m").strip().lower()
        return "1h" if text == "60m" else text

    def _find_first_list_of_dicts(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        for value in payload.values():
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                return value
        return []

    def _normalize_account_filters(self, filters: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(filters or {})
        payload.setdefault("acct_no", self.account_no)
        return payload

    def _row_looks_filled(self, row: dict[str, Any]) -> bool:
        text = json.dumps(row, ensure_ascii=False).lower()
        return any(token in text for token in ["fill", "exec", "chegyul", "체결"])

    def _unwrap_single_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        for value in payload.values():
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]
        return payload

    def _pick(self, data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return ""

    def _normalize_bar_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        date_text = str(self._pick(row, "dt", "date", "trde_date", "bs_dt") or "").strip()
        time_text = str(self._pick(row, "tm", "time", "trde_tm", "tm_tp") or "").strip()
        if len(date_text) == 8 and len("".join(ch for ch in time_text if ch.isdigit())) >= 4:
            timestamp = self._combine_timestamp(date_text, time_text)
        else:
            timestamp = self._parse_any_timestamp(str(self._pick(row, "dtm", "timestamp", "cntr_tm") or ""))
        if not timestamp:
            return None
        return {
            "timestamp": timestamp,
            "open": self._to_float(self._pick(row, "open_pric", "stt_pric")),
            "high": self._to_float(self._pick(row, "high_pric", "high")),
            "low": self._to_float(self._pick(row, "low_pric", "low")),
            "close": self._to_float(self._pick(row, "cur_prc", "close_pric", "last_pric")),
            "volume": self._to_float(self._pick(row, "trde_qty", "acc_trde_qty", "qty")),
        }

    def _combine_timestamp(self, date_text: str, time_text: str) -> str | None:
        digits_date = "".join(ch for ch in date_text if ch.isdigit())
        digits_time = "".join(ch for ch in time_text if ch.isdigit())
        if len(digits_time) == 4:
            digits_time = f"{digits_time}00"
        if len(digits_date) != 8 or len(digits_time) < 6:
            return None
        try:
            return datetime.strptime(f"{digits_date}{digits_time[:6]}", "%Y%m%d%H%M%S").isoformat()
        except ValueError:
            return None

    def _parse_any_timestamp(self, text: str) -> str | None:
        digits = "".join(ch for ch in text if ch.isdigit())
        for fmt, size in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12)):
            if len(digits) >= size:
                try:
                    dt = datetime.strptime(digits[:size], fmt)
                    return dt.isoformat()
                except ValueError:
                    continue
        return None

    def _filter_intraday_rows(self, rows: list[dict[str, Any]], *, start: str, end: str) -> list[dict[str, Any]]:
        start_marker = self._normalize_time_filter(start)
        end_marker = self._normalize_time_filter(end)
        filtered: list[dict[str, Any]] = []
        for row in rows:
            time_fragment = row["timestamp"][11:19]
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
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            return f"{digits[-6:-4]}:{digits[-4:-2]}:{digits[-2:]}"
        if len(digits) == 4:
            return f"{digits[:2]}:{digits[2:]}:00"
        return ""

    def _aggregate_bars(self, rows: list[dict[str, Any]], interval: str) -> list[dict[str, Any]]:
        step = self._interval_minutes(interval)
        if step == 1:
            return rows
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
                    "high": max(item["high"] for item in group),
                    "low": min(item["low"] for item in group),
                    "close": group[-1]["close"],
                    "volume": sum(item["volume"] for item in group),
                }
            )
        return aggregated

    def _interval_minutes(self, interval: str) -> int:
        mapping = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}
        return mapping.get(interval, 1)

    def _to_float(self, value: Any) -> float:
        if value in (None, "", "-"):
            return 0.0
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    def _today_kst(self) -> datetime:
        return self._now_kst()

    def _now_kst(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None) + KST

    def _load_websocket_connect(self) -> Any:
        try:
            import websockets  # type: ignore
        except ImportError as exc:
            raise RuntimeError("websockets dependency is required for Kiwoom realtime support") from exc
        return websockets.connect
