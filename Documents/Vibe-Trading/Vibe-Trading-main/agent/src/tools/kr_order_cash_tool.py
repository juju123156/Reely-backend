"""Tool: KR 현금 주문 (매수/매도/취소/정정/매수가능조회)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.brokers import get_broker_adapter


class KROrderCashTool(BaseTool):
    """KR 주식 현금 주문 실행 툴.

    action:
      - buy             : 매수 주문
      - sell            : 매도 주문
      - cancel          : 미체결 주문 취소
      - modify          : 미체결 주문 정정 (단가 변경)
      - inquire_buyable : 매수 가능 수량/금액 조회
    """

    name = "kr_order_cash"
    description = (
        "KR 주식 현금 주문. "
        "action=buy/sell 로 매수·매도, action=cancel 로 취소, "
        "action=modify 로 단가 정정, action=inquire_buyable 로 매수 가능 수량 확인. "
        "dry_run=true 로 API 호출 없이 파라미터 확인 가능."
    )
    is_readonly = False
    repeatable = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["buy", "sell", "cancel", "modify", "inquire_buyable"],
                "description": "수행할 액션",
            },
            "symbol": {
                "type": "string",
                "description": "종목코드 6자리 (예: '005930')",
            },
            "qty": {
                "type": "integer",
                "description": "주문 수량 (buy/sell/cancel/modify 시 필요)",
            },
            "price": {
                "type": "number",
                "description": "주문 단가. 0 또는 생략 시 시장가. modify 시 변경할 단가.",
            },
            "order_type": {
                "type": "string",
                "enum": ["auto", "limit", "market"],
                "description": "주문 유형. auto=price>0이면 지정가, 기본값 auto",
            },
            "order_no": {
                "type": "string",
                "description": "cancel/modify 시 필요. place 결과의 order_no",
            },
            "krx_org_no": {
                "type": "string",
                "description": "cancel/modify 시 필요. place 결과의 krx_org_no",
            },
            "cancel_all": {
                "type": "boolean",
                "description": "cancel 시 잔량 전부 취소 여부 (기본 true)",
            },
            "env_dv": {
                "type": "string",
                "enum": ["demo", "real"],
                "description": "demo=모의투자, real=실전. 생략 시 브로커 기본값 사용",
            },
            "broker_name": {
                "type": "string",
                "description": "브로커 이름 (기본 'kis')",
            },
            "dry_run": {
                "type": "boolean",
                "description": "true 이면 API 호출 없이 파라미터만 반환 (기본 false)",
            },
        },
        "required": ["action", "symbol"],
    }

    def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "")
        symbol = str(kwargs.get("symbol") or "")
        broker_name = str(kwargs.get("broker_name") or "kis")
        env_dv = kwargs.get("env_dv") or None
        dry_run = bool(kwargs.get("dry_run") or False)

        try:
            broker = get_broker_adapter(broker_name)
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"broker not found: {exc}"}, ensure_ascii=False)

        if action in ("buy", "sell"):
            qty = int(kwargs.get("qty") or 0)
            price = float(kwargs.get("price") or 0.0)
            order_type = str(kwargs.get("order_type") or "auto")
            result = broker.place_order_cash(
                symbol, action, qty=qty, price=price,
                order_type=order_type, env_dv=env_dv, dry_run=dry_run,
            )
            return json.dumps(result, ensure_ascii=False)

        if action == "cancel":
            order_no = str(kwargs.get("order_no") or "")
            krx_org_no = str(kwargs.get("krx_org_no") or "")
            qty = int(kwargs.get("qty") or 0)
            cancel_all = bool(kwargs.get("cancel_all") if kwargs.get("cancel_all") is not None else True)
            if not order_no or not krx_org_no:
                return json.dumps({"status": "error", "error": "order_no, krx_org_no 필요"}, ensure_ascii=False)
            result = broker.cancel_order(krx_org_no, order_no, symbol, qty, cancel_all=cancel_all, env_dv=env_dv)
            return json.dumps(result, ensure_ascii=False)

        if action == "modify":
            order_no = str(kwargs.get("order_no") or "")
            krx_org_no = str(kwargs.get("krx_org_no") or "")
            qty = int(kwargs.get("qty") or 0)
            price = float(kwargs.get("price") or 0.0)
            if not order_no or not krx_org_no or not price:
                return json.dumps({"status": "error", "error": "order_no, krx_org_no, price 필요"}, ensure_ascii=False)
            result = broker.modify_order(krx_org_no, order_no, symbol, qty, price, env_dv=env_dv)
            return json.dumps(result, ensure_ascii=False)

        if action == "inquire_buyable":
            price = float(kwargs.get("price") or 0.0)
            order_type = str(kwargs.get("order_type") or "market")
            result = broker.inquire_psbl_order(symbol, price, order_type=order_type, env_dv=env_dv)
            return json.dumps(result, ensure_ascii=False)

        return json.dumps({"status": "error", "error": f"unknown action: {action}"}, ensure_ascii=False)
