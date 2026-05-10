"""Tool: 스캘핑 봇 제어 (시작/정지/상태 조회)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)


class ScalpingTool(BaseTool):
    """스캘핑 자동매매 봇 제어 툴.

    action:
      - start  : 봇 시작. symbols 목록 또는 MarketScanner 자동 선정
      - stop   : 봇 정지 (Kill Switch → 전량 청산)
      - status : 현재 상태 조회 (포지션, 리스크, 저널, WS 연결)
      - pause  : 신규 진입 중단 (기존 포지션 유지)
      - resume : pause 해제
    """

    name = "scalping_bot"
    description = (
        "첫 눌림 후 재돌파 스캘핑 자동매매 봇 제어. "
        "action=start 로 시작, action=stop 으로 Kill Switch 발동, "
        "action=status 로 포지션·리스크·거래 저널 조회. "
        "dry_run=true 이면 실제 주문 없이 종이 거래."
    )
    is_readonly = False
    repeatable = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status", "pause", "resume"],
                "description": "수행할 액션",
            },
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "action=start 시 감시할 종목 코드 목록. "
                    "생략 시 MarketScanner가 자동 선정."
                ),
            },
            "dry_run": {
                "type": "boolean",
                "description": "true=종이거래 (기본값 true)",
            },
        },
        "required": ["action"],
    }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        symbols: list[str] = kwargs.get("symbols") or []
        dry_run: bool = kwargs.get("dry_run", True)

        try:
            if action == "start":
                result = self._run_async(self._do_start(symbols, dry_run))
            elif action == "stop":
                result = self._run_async(self._do_stop())
            elif action == "status":
                result = self._do_status()
            elif action == "pause":
                result = self._do_pause()
            elif action == "resume":
                result = self._do_resume()
            else:
                result = {"status": "error", "message": f"알 수 없는 action: {action}"}
        except Exception as exc:
            logger.exception("ScalpingTool error")
            result = {"status": "error", "message": str(exc)}

        return json.dumps(result, ensure_ascii=False)

    # ── async bridge ─────────────────────────────────────────────────────────

    @staticmethod
    def _run_async(coro) -> dict:
        """실행 중인 이벤트 루프가 있으면 새 스레드에서, 없으면 asyncio.run()."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=30)
        else:
            return asyncio.run(coro)

    # ── start ────────────────────────────────────────────────────────────────

    async def _do_start(self, symbols: list[str], dry_run: bool) -> dict:
        from src.trading.scalping.bot import BotStatus, get_bot, start_bot
        from src.trading.scalping.config import ScalpingBotConfig

        bot = get_bot()
        if bot and bot._status == BotStatus.RUNNING:
            return {
                "status": "already_running",
                "message": "봇이 이미 실행 중입니다.",
                "bot_status": bot.status_dict(),
            }

        try:
            cfg = ScalpingBotConfig()
        except Exception:
            cfg = None

        if cfg and hasattr(cfg, "strategy") and cfg.strategy:
            cfg.strategy.dry_run = dry_run

        logger.info("ScalpingTool: starting bot dry_run=%s symbols=%s", dry_run, symbols)
        bot = await start_bot(symbols, cfg)

        return {
            "status": "started",
            "dry_run": dry_run,
            "symbols": symbols or ["auto-scan"],
            "bot_status": bot.status_dict(),
        }

    # ── stop ─────────────────────────────────────────────────────────────────

    async def _do_stop(self) -> dict:
        from src.trading.scalping.bot import KillReason, get_bot, stop_bot

        bot = get_bot()
        if not bot:
            return {"status": "not_running", "message": "실행 중인 봇이 없습니다."}

        last_status = bot.status_dict()
        await stop_bot()

        return {
            "status": "stopped",
            "kill_reason": KillReason.MANUAL,
            "final_journal": last_status.get("journal", {}),
            "final_risk": last_status.get("risk", {}),
        }

    # ── status ───────────────────────────────────────────────────────────────

    def _do_status(self) -> dict:
        from src.trading.scalping.bot import get_bot
        bot = get_bot()
        if not bot:
            return {"status": "not_running"}
        return {"status": "ok", **bot.status_dict()}

    # ── pause / resume ───────────────────────────────────────────────────────

    def _do_pause(self) -> dict:
        from src.trading.scalping.bot import BotStatus, get_bot
        bot = get_bot()
        if not bot:
            return {"status": "not_running"}
        if bot._status != BotStatus.RUNNING:
            return {"status": "error", "message": f"RUNNING 상태가 아님: {bot._status.value}"}
        bot._status = BotStatus.PAUSED
        logger.info("ScalpingTool: bot paused")
        return {"status": "paused"}

    def _do_resume(self) -> dict:
        from src.trading.scalping.bot import BotStatus, get_bot
        bot = get_bot()
        if not bot:
            return {"status": "not_running"}
        if bot._status != BotStatus.PAUSED:
            return {"status": "error", "message": f"PAUSED 상태가 아님: {bot._status.value}"}
        bot._status = BotStatus.RUNNING
        logger.info("ScalpingTool: bot resumed")
        return {"status": "running"}
