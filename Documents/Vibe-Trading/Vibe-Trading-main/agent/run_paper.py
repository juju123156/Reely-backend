"""모의투자 봇 실행 스크립트."""
import asyncio
import logging
import signal
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env.paper"), override=True)

from src.trading.scalping.bot import start_bot, stop_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("paper_trading.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_paper")


async def main() -> None:
    logger.info("=== 모의투자 봇 시작 (KIS VTS) ===")

    bot = await start_bot(symbols=[], config=None)

    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str) -> None:
        logger.info("Signal %s received — stopping bot", sig_name)
        loop.create_task(stop_bot())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))

    logger.info("봇 실행 중 — Ctrl+C로 종료")
    await bot._kill_event.wait()
    logger.info("=== 봇 종료 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
