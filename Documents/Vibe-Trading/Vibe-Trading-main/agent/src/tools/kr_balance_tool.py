"""Tool: KR 주식 잔고 조회 (보유종목 + 예수금)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.brokers import get_broker_adapter


class KRBalanceTool(BaseTool):
    """KR 주식 잔고 조회 툴.

    action:
      - holdings : 보유 종목 목록 + 계좌 요약 (예수금, 총평가금액, 평가손익)
    """

    name = "kr_balance"
    description = (
        "KR 주식 잔고 조회. "
        "보유 종목 목록(종목코드·수량·평균단가·현재가·평가손익·수익률)과 "
        "계좌 요약(예수금·총평가금액·평가손익합계)을 반환한다. "
        "주문 후 잔고를 재확인하거나 포지션 크기를 계산할 때 사용."
    )
    is_readonly = True
    repeatable = True

    parameters = {
        "type": "object",
        "properties": {
            "env_dv": {
                "type": "string",
                "enum": ["demo", "real"],
                "description": "demo=모의투자, real=실전. 생략 시 브로커 기본값 사용",
            },
            "broker_name": {
                "type": "string",
                "description": "브로커 이름 (기본 'kis')",
            },
            "ctx_fk": {
                "type": "string",
                "description": "다음 페이지 조회 시 이전 응답의 next_ctx.fk 값",
            },
            "ctx_nk": {
                "type": "string",
                "description": "다음 페이지 조회 시 이전 응답의 next_ctx.nk 값",
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        broker_name = str(kwargs.get("broker_name") or "kis")
        env_dv = kwargs.get("env_dv") or None
        ctx_fk = str(kwargs.get("ctx_fk") or "")
        ctx_nk = str(kwargs.get("ctx_nk") or "")

        try:
            broker = get_broker_adapter(broker_name)
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"broker not found: {exc}"}, ensure_ascii=False)

        result = broker.inquire_balance(env_dv=env_dv, ctx_fk=ctx_fk, ctx_nk=ctx_nk)
        return json.dumps(result, ensure_ascii=False)
