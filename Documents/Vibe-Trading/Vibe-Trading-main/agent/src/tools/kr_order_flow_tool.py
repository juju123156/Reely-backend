"""Tool: KR 단타 수급 모니터링 — 추매/매도 신호."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.kr_order_flow_runner import get_runner


class KROrderFlowTool(BaseTool):
    """KR 단타 수급 모니터링 러너를 시작/중지/조회하는 툴.

    수급 신호 3종:
      - pyramid : 추매 조건 충족 (체결강도>130, 호가잔량비>1.5, 거래량배율>1.5, 수익>0.5%)
      - exit    : 매도 조건 충족 (체결강도<70 or 호가잔량비<0.7 or 클라이맥스)
      - hold    : 대기
    """

    name = "kr_order_flow"
    description = (
        "KR 단타 수급 모니터링. "
        "action=start 로 백그라운드 폴링 시작, action=status 로 현재 신호 조회, "
        "action=stop 으로 중지. "
        "signals 필드에서 각 종목의 추매/매도/홀드 신호와 체결강도·호가잔량비·거래량배율을 확인."
    )
    is_readonly = False
    repeatable = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status", "update_position", "clear_position"],
                "description": "수행할 액션",
            },
            "task_id": {
                "type": "string",
                "description": "stop / status / update_position / clear_position 시 필요한 태스크 ID",
            },
            "broker_name": {
                "type": "string",
                "description": "start 시 브로커 이름 (kis 또는 kiwoom)",
            },
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "start 시 모니터링할 종목 코드 리스트",
            },
            "poll_interval": {
                "type": "number",
                "description": "폴링 주기 (초). 단타 권장: 2~5초 (기본값 2)",
            },
            "env_dv": {
                "type": "string",
                "description": "demo (모의투자) 또는 real (실거래)",
            },
            "position_info": {
                "type": "object",
                "description": "보유 포지션 정보 {symbol: {entry_price, size}}",
            },
            "symbol": {
                "type": "string",
                "description": "update_position / clear_position 시 대상 종목",
            },
            "entry_price": {
                "type": "number",
                "description": "update_position 시 진입가",
            },
            "size": {
                "type": "number",
                "description": "update_position 시 보유 수량",
            },
            "pyramid_es_min": {"type": "number", "description": "추매 체결강도 최솟값 (기본 130)"},
            "pyramid_ob_min": {"type": "number", "description": "추매 호가잔량비 최솟값 (기본 1.5)"},
            "pyramid_pnl_min": {"type": "number", "description": "추매 최소 미실현수익률 (기본 0.005 = 0.5%)"},
            "exit_es_max": {"type": "number", "description": "매도 체결강도 상한 (기본 70)"},
            "exit_ob_max": {"type": "number", "description": "매도 호가잔량비 하한 (기본 0.7)"},
            "use_ws": {
                "type": "boolean",
                "description": "true 이면 H0STCNT0 WebSocket 실시간 모드 (KIS 전용). false(기본)이면 REST 폴링.",
            },
        },
        "required": ["action"],
    }

    def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "")
        runner = get_runner()

        if action == "start":
            symbols = [str(s) for s in (kwargs.get("symbols") or [])]
            if not symbols:
                return json.dumps({"status": "error", "error": "symbols 필드가 비어있습니다"}, ensure_ascii=False)

            result = runner.start(
                broker_name=str(kwargs.get("broker_name") or "kis"),
                symbols=symbols,
                poll_interval=float(kwargs.get("poll_interval") or 2.0),
                env_dv=kwargs.get("env_dv"),
                position_info=kwargs.get("position_info"),
                use_ws=bool(kwargs.get("use_ws") or False),
                pyramid_es_min=float(kwargs.get("pyramid_es_min") or 130.0),
                pyramid_ob_min=float(kwargs.get("pyramid_ob_min") or 1.5),
                pyramid_pnl_min=float(kwargs.get("pyramid_pnl_min") or 0.005),
                exit_es_max=float(kwargs.get("exit_es_max") or 70.0),
                exit_ob_max=float(kwargs.get("exit_ob_max") or 0.7),
            )
            return json.dumps(result, ensure_ascii=False)

        if action == "stop":
            task_id = str(kwargs.get("task_id") or "")
            if not task_id:
                return json.dumps({"status": "error", "error": "task_id 필요"}, ensure_ascii=False)
            return json.dumps(runner.stop(task_id), ensure_ascii=False)

        if action == "status":
            task_id = kwargs.get("task_id")
            return json.dumps(runner.status(task_id), ensure_ascii=False, default=str)

        if action == "update_position":
            task_id = str(kwargs.get("task_id") or "")
            symbol = str(kwargs.get("symbol") or "")
            entry_price = float(kwargs.get("entry_price") or 0.0)
            size = float(kwargs.get("size") or 0.0)
            if not task_id or not symbol:
                return json.dumps({"status": "error", "error": "task_id, symbol 필요"}, ensure_ascii=False)
            runner.update_position(task_id, symbol, entry_price, size)
            return json.dumps({"status": "ok", "symbol": symbol, "entry_price": entry_price}, ensure_ascii=False)

        if action == "clear_position":
            task_id = str(kwargs.get("task_id") or "")
            symbol = str(kwargs.get("symbol") or "")
            if not task_id or not symbol:
                return json.dumps({"status": "error", "error": "task_id, symbol 필요"}, ensure_ascii=False)
            runner.clear_position(task_id, symbol)
            return json.dumps({"status": "ok", "symbol": symbol, "cleared": True}, ensure_ascii=False)

        return json.dumps({"status": "error", "error": f"unknown action: {action}"}, ensure_ascii=False)
