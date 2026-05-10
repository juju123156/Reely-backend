from __future__ import annotations

from src.brokers.base import BrokerOrderRequest
from src.brokers.kiwoom import KiwoomBrokerAdapter


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

    def post(self, url: str, json: dict, headers: dict, timeout: float) -> _FakeResponse:
        self.post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if url.endswith("/oauth2/token"):
            return _FakeResponse(
                {
                    "token": "kw-123",
                    "expires_dt": "20260426235959",
                    "return_code": 0,
                    "return_msg": "ok",
                }
            )
        if url.endswith("/api/dostk/mrkcond"):
            return _FakeResponse(
                {
                    "return_code": 0,
                    "return_msg": "ok",
                    "price": {
                        "cur_prc": "70500",
                        "open_pric": "70000",
                        "high_pric": "70600",
                        "low_pric": "69800",
                        "trde_qty": "123456",
                        "acc_trde_prica": "8712345",
                        "pred_pre": "500",
                        "flu_rt": "0.71",
                        "tm": "091500",
                    },
                }
            )
        if url.endswith("/api/dostk/acnt"):
            return _FakeResponse(
                {
                    "return_code": 0,
                    "return_msg": "ok",
                    "orders": [
                        {"ord_no": "1111111", "status": "open"},
                        {"ord_no": "2222222", "체결수량": "2", "exec_qty": "2"},
                    ],
                }
            )
        if url.endswith("/api/dostk/ordr"):
            api_id = headers.get("api-id")
            return _FakeResponse(
                {
                    "return_code": 0,
                    "return_msg": "ok",
                    "ord_no": "1234567" if api_id == "kt10000" else "7654321",
                    "dmst_stex_tp": json["dmst_stex_tp"],
                }
            )
        return _FakeResponse(
            {
                "return_code": 0,
                "return_msg": "ok",
                "chart": [
                    {"dt": "20260426", "tm": "0901", "open_pric": "70000", "high_pric": "70100", "low_pric": "69900", "cur_prc": "70050", "trde_qty": "100"},
                    {"dt": "20260426", "tm": "0902", "open_pric": "70050", "high_pric": "70200", "low_pric": "70000", "cur_prc": "70150", "trde_qty": "200"},
                    {"dt": "20260426", "tm": "0903", "open_pric": "70150", "high_pric": "70300", "low_pric": "70100", "cur_prc": "70250", "trde_qty": "300"},
                    {"dt": "20260426", "tm": "0904", "open_pric": "70250", "high_pric": "70400", "low_pric": "70200", "cur_prc": "70350", "trde_qty": "400"},
                    {"dt": "20260426", "tm": "0905", "open_pric": "70350", "high_pric": "70500", "low_pric": "70300", "cur_prc": "70450", "trde_qty": "500"},
                    {"dt": "20260426", "tm": "0906", "open_pric": "70450", "high_pric": "70600", "low_pric": "70400", "cur_prc": "70550", "trde_qty": "600"},
                ],
            }
        )


def _build_adapter(session: _FakeSession | None = None) -> KiwoomBrokerAdapter:
    return KiwoomBrokerAdapter(
        app_key="real-app",
        secret_key="real-secret",
        account_no="12345678",
        paper_app_key="paper-app",
        paper_secret_key="paper-secret",
        session=session or _FakeSession(),
    )


class _FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = list(messages)
        self.sent: list[dict] = []

    async def __aenter__(self) -> "_FakeWebSocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def send(self, payload: str) -> None:
        import json as _json

        self.sent.append(_json.loads(payload))

    async def recv(self) -> str:
        import json as _json

        if not self._messages:
            raise TimeoutError("no more messages")
        return _json.dumps(self._messages.pop(0), ensure_ascii=False)


def test_issue_access_token_uses_cache() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    first = adapter.issue_access_token()
    second = adapter.issue_access_token()

    assert first["status"] == "ok"
    assert second["cached"] is True
    assert len(session.post_calls) == 1


def test_get_quote_standardizes_kiwoom_payload() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    result = adapter.get_quote("005930.KS")

    assert result["status"] == "ok"
    assert result["symbol"] == "005930"
    assert result["quote"]["last"] == 70500.0
    assert result["quote"]["volume"] == 123456.0


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


def test_place_order_requires_quantity_for_live() -> None:
    adapter = _build_adapter(_FakeSession())

    result = adapter.place_order(
        BrokerOrderRequest(symbol="005930.KS", side="BUY", qty_policy="fixed"),
        mode="live",
        dry_run=False,
    )

    assert result.status == "error"
    assert "quantity" in result.message


def test_place_order_submits_live_kiwoom_request() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    result = adapter.place_order(
        BrokerOrderRequest(
            symbol="005930.KS",
            side="BUY",
            qty_policy="fixed",
            limit_policy="market",
            quantity=3,
            metadata={"market_code": "KRX"},
        ),
        mode="live",
        dry_run=False,
    )

    assert result.status == "accepted"
    assert result.order_id == "1234567"
    order_call = session.post_calls[-1]
    assert order_call["url"].endswith("/api/dostk/ordr")
    assert order_call["headers"]["api-id"] == "kt10000"
    assert order_call["json"]["ord_qty"] == "3"
    assert order_call["json"]["trde_tp"] == "3"


def test_modify_and_cancel_order_use_correct_api_ids() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    modify = adapter.modify_order("1234567", symbol="005930.KS", quantity=1, limit_price=70500)
    cancel = adapter.cancel_order("1234567", symbol="005930.KS", quantity=1)

    assert modify["status"] == "ok"
    assert cancel["status"] == "ok"
    assert session.post_calls[-2]["headers"]["api-id"] == "kt10002"
    assert session.post_calls[-1]["headers"]["api-id"] == "kt10003"


def test_get_orders_and_fills_read_account_endpoint() -> None:
    session = _FakeSession()
    adapter = _build_adapter(session)

    orders = adapter.get_orders()
    fills = adapter.get_fills()

    assert orders["status"] == "ok"
    assert len(orders["orders"]) == 2
    assert fills["status"] == "ok"
    assert len(fills["fills"]) == 1
    assert fills["fills"][0]["ord_no"] == "2222222"


def test_build_quote_subscription_payload() -> None:
    adapter = _build_adapter(_FakeSession())

    payload = adapter.build_quote_subscription(["005930.KS", "000660.KS"], quote_types=["0B", "0C"])

    assert payload["trnm"] == "REG"
    assert payload["data"][0]["item"] == ["005930", "000660"]
    assert payload["data"][0]["type"] == ["0B", "0C"]


def test_list_conditions_and_condition_search_via_fake_websocket() -> None:
    session = _FakeSession()
    fake_socket = _FakeWebSocket(
        [
            {"trnm": "LOGIN", "return_code": 0, "return_msg": ""},
            {"trnm": "CNSRLST", "return_code": 0, "data": [["0", "조건1"], ["1", "조건2"]]},
        ]
    )
    adapter = KiwoomBrokerAdapter(
        app_key="real-app",
        secret_key="real-secret",
        account_no="12345678",
        session=session,
        websocket_factory=lambda uri: fake_socket,
    )

    result = adapter.list_conditions()

    assert result["status"] == "ok"
    assert result["conditions"] == [{"seq": "0", "name": "조건1"}, {"seq": "1", "name": "조건2"}]
    assert fake_socket.sent[0]["trnm"] == "LOGIN"
    assert fake_socket.sent[1]["trnm"] == "CNSRLST"


def test_run_and_release_condition_search_build_expected_messages() -> None:
    session = _FakeSession()
    fake_socket = _FakeWebSocket(
        [
            {"trnm": "LOGIN", "return_code": 0, "return_msg": ""},
            {"trnm": "CNSRREQ", "return_code": 0, "data": [{"stk_cd": "005930"}]},
        ]
    )
    adapter = KiwoomBrokerAdapter(
        app_key="real-app",
        secret_key="real-secret",
        account_no="12345678",
        session=session,
        websocket_factory=lambda uri: fake_socket,
    )

    result = adapter.run_condition_search("7", realtime=True)

    assert result["status"] == "ok"
    assert fake_socket.sent[1] == {"trnm": "CNSRREQ", "seq": "7", "search_tp": "1"}
