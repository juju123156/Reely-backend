"""KR 단타 수급 러너.

두 가지 모드:
  REST 폴링 (기본, use_ws=False):
    poll_interval 마다 KIS API 3개를 순차 호출
    (get_quote → get_execution_detail → get_order_book)
    레이턴시: ~2~5초 주기, API timeout=3.0s

  WebSocket 실시간 (use_ws=True):
    H0STCNT0 틱 스트림을 구독하여 체결마다 즉시 신호 재평가
    레이턴시: 체결 발생 즉시 (<100ms)
    KIS 브로커(kis)에서만 지원

OrderFlowState 계산은 양쪽 모두 O(1).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from src.brokers import get_broker_adapter
from src.trading.kr_order_flow import OrderFlowBook, OrderFlowSignal

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KROrderFlowRunner:
    """종목별 수급 상태를 주기적으로 갱신하고 신호를 기록하는 백그라운드 러너."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        broker_name: str,
        symbols: list[str],
        poll_interval: float = 2.0,
        env_dv: str | None = None,
        position_info: dict[str, dict[str, float]] | None = None,
        max_cycles: int | None = None,
        use_ws: bool = False,
        # OrderFlowState 파라미터
        window: int = 20,
        pyramid_es_min: float = 130.0,
        pyramid_ob_min: float = 1.5,
        pyramid_vol_min: float = 1.5,
        pyramid_pnl_min: float = 0.005,
        exit_es_max: float = 70.0,
        exit_ob_max: float = 0.7,
        exit_vol_climax: float = 3.0,
    ) -> dict[str, Any]:
        """수급 모니터링을 백그라운드 스레드로 시작.

        Args:
            broker_name    : "kis" or "kiwoom"
            symbols        : 모니터링할 종목 코드 리스트
            poll_interval  : 폴링 주기 (초). REST 모드에서만 사용, 단타는 2~5초 권장
            env_dv         : "demo" (모의) or "real" (실거래)
            position_info  : {symbol: {"entry_price": ..., "size": ...}}
                             포지션 보유 중인 종목 정보. 없으면 빈 dict.
            max_cycles     : None 이면 무한 반복 (REST 모드 전용)
            use_ws         : True 이면 H0STCNT0 WebSocket 실시간 모드 (KIS 전용)
        """
        task_id = uuid.uuid4().hex[:8]
        stop_event = threading.Event()

        book = OrderFlowBook(
            window=window,
            pyramid_es_min=pyramid_es_min,
            pyramid_ob_min=pyramid_ob_min,
            pyramid_vol_min=pyramid_vol_min,
            pyramid_pnl_min=pyramid_pnl_min,
            exit_es_max=exit_es_max,
            exit_ob_max=exit_ob_max,
            exit_vol_climax=exit_vol_climax,
        )
        # 초기 상태 생성
        for sym in symbols:
            book.get_or_create(sym)

        task: dict[str, Any] = {
            "task_id": task_id,
            "status": "running",
            "mode": "ws" if use_ws else "rest",
            "broker_name": broker_name,
            "symbols": list(symbols),
            "poll_interval": poll_interval,
            "env_dv": env_dv or "",
            "max_cycles": max_cycles,
            "iterations": 0,
            "signals": {},       # {symbol: {"action": ..., "reason": ..., ...}}
            "last_error": "",
            "updated_at": _now_iso(),
            "_stop_event": stop_event,
            "_book": book,
            "_position_info": dict(position_info or {}),
        }

        with self._lock:
            self._tasks[task_id] = task

        if use_ws:
            if broker_name != "kis":
                task["status"] = "error"
                task["last_error"] = "WebSocket 모드는 KIS 브로커만 지원합니다"
                return self._public(task_id)
            thread = threading.Thread(
                target=self._ws_loop,
                args=(task_id, env_dv),
                daemon=True,
            )
        else:
            thread = threading.Thread(
                target=self._poll_loop,
                args=(task_id,),
                daemon=True,
            )
        task["_thread"] = thread
        thread.start()
        logger.info("KROrderFlowRunner started: task=%s mode=%s symbols=%s",
                    task_id, "ws" if use_ws else "rest", symbols)
        return self._public(task_id)

    def stop(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"status": "error", "error": f"unknown task: {task_id}"}
            task["_stop_event"].set()
            task["status"] = "stopping"
        return self._public(task_id)

    def status(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if task_id:
                task = self._tasks.get(task_id)
                if not task:
                    return {"status": "error", "error": f"unknown task: {task_id}"}
                return {"status": "ok", "task": self._strip(task)}
            return {
                "status": "ok",
                "tasks": [self._strip(t) for t in self._tasks.values()],
            }

    def update_position(self, task_id: str, symbol: str, entry_price: float, size: float) -> None:
        """포지션 진입 시 호출 — baseline 설정."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["_position_info"][symbol] = {"entry_price": entry_price, "size": size}
            book: OrderFlowBook = task["_book"]
        book.get_or_create(symbol).set_baseline()

    def clear_position(self, task_id: str, symbol: str) -> None:
        """포지션 청산 시 호출."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["_position_info"].pop(symbol, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ws_loop(self, task_id: str, env_dv: str | None) -> None:
        """WebSocket 실시간 모드 메인 루프 (데몬 스레드)."""
        from src.brokers import get_broker_adapter
        from src.brokers.kis_websocket import make_tick_subscriber, TickData

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            symbols = list(task["symbols"])
            book: OrderFlowBook = task["_book"]

        def on_tick(tick: TickData) -> None:
            with self._lock:
                t = self._tasks.get(task_id)
                if not t or t["_stop_event"].is_set():
                    return
                book_ref: OrderFlowBook = t["_book"]
                position_info: dict = dict(t["_position_info"])

            state = book_ref.get_or_create(tick.symbol)
            state.update_poll(
                price=tick.price,
                buy_vol_total=tick.buy_vol_total,
                sell_vol_total=tick.sell_vol_total,
                bid_qty=tick.bid_qty,
                ask_qty=tick.ask_qty,
            )

            pos = position_info.get(tick.symbol)
            in_position = pos is not None
            unrealized_pnl = 0.0
            if in_position and tick.price > 0 and pos.get("entry_price", 0) > 0:
                unrealized_pnl = (tick.price - pos["entry_price"]) / pos["entry_price"]

            sig = state.evaluate(in_position=in_position, unrealized_pnl=unrealized_pnl)

            sig_dict = {
                "symbol": tick.symbol,
                "action": sig.action,
                "reason": sig.reason,
                "exec_strength": round(sig.exec_strength, 1),
                "ob_imbalance": round(sig.ob_imbalance, 3),
                "vol_ratio": round(sig.vol_ratio, 2),
                "price": tick.price,
                "unrealized_pnl": round(unrealized_pnl, 4),
                "in_position": in_position,
            }

            with self._lock:
                t = self._tasks.get(task_id)
                if t:
                    t["signals"][tick.symbol] = sig_dict
                    t["iterations"] = t["iterations"] + 1
                    t["updated_at"] = _now_iso()

        try:
            adapter = get_broker_adapter("kis")
            subscriber = make_tick_subscriber(adapter, symbols, on_tick, env=env_dv or "demo")
            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task["_ws_subscriber"] = subscriber

            subscriber.start_background()

            # stop_event를 기다리며 WS 스레드가 살아있는지 감시
            stop_event: threading.Event = task["_stop_event"]
            while not stop_event.is_set():
                stop_event.wait(timeout=1.0)

            subscriber.stop()

        except Exception as exc:
            logger.error("KROrderFlowRunner WS loop error: %s", exc)
            with self._lock:
                t = self._tasks.get(task_id)
                if t:
                    t["last_error"] = str(exc)
        finally:
            with self._lock:
                t = self._tasks.get(task_id)
                if t:
                    t["status"] = "stopped"
                    t["updated_at"] = _now_iso()

    def _poll_loop(self, task_id: str) -> None:
        while True:
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    return
                if task["_stop_event"].is_set():
                    task["status"] = "stopped"
                    task["updated_at"] = _now_iso()
                    return

                broker_name = task["broker_name"]
                symbols = list(task["symbols"])
                env_dv = task["env_dv"] or None
                poll_interval = float(task["poll_interval"])
                max_cycles = task["max_cycles"]
                iterations = int(task["iterations"])
                book: OrderFlowBook = task["_book"]
                position_info: dict = dict(task["_position_info"])

            if max_cycles is not None and iterations >= max_cycles:
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task:
                        task["status"] = "completed"
                        task["updated_at"] = _now_iso()
                return

            t0 = time.monotonic()
            new_signals: dict[str, Any] = {}
            last_error = ""

            try:
                adapter = get_broker_adapter(broker_name)
                # timeout 단축: 단타는 레이턴시 우선
                if hasattr(adapter, "timeout"):
                    adapter.timeout = 3.0

                for sym in symbols:
                    sig_dict = self._poll_symbol(adapter, sym, env_dv, book, position_info)
                    new_signals[sym] = sig_dict

            except Exception as exc:
                last_error = str(exc)
                logger.debug("KROrderFlowRunner poll error: %s", exc)

            elapsed = time.monotonic() - t0

            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task["iterations"] = iterations + 1
                    task["signals"] = new_signals
                    task["last_error"] = last_error
                    task["updated_at"] = _now_iso()

            sleep_time = max(0.0, poll_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _poll_symbol(
        self,
        adapter: Any,
        symbol: str,
        env_dv: str | None,
        book: OrderFlowBook,
        position_info: dict,
    ) -> dict[str, Any]:
        state = book.get_or_create(symbol)

        # 1) 현재가
        quote = adapter.get_quote(symbol, env_dv=env_dv)
        price = float((quote.get("quote") or {}).get("last") or 0.0)

        buy_vol_total = 0.0
        sell_vol_total = 0.0
        bid_qty = 0.0
        ask_qty = 0.0

        # 2) 체결 상세 (체결강도 계산용)
        if hasattr(adapter, "get_execution_detail"):
            exec_data = adapter.get_execution_detail(symbol, env_dv=env_dv)
            if exec_data.get("status") == "ok":
                buy_vol_total = float(exec_data.get("buy_vol_total") or 0.0)
                sell_vol_total = float(exec_data.get("sell_vol_total") or 0.0)

        # 3) 호가 잔량 (호가잔량비 계산용)
        if hasattr(adapter, "get_order_book"):
            ob_data = adapter.get_order_book(symbol, env_dv=env_dv)
            if ob_data.get("status") == "ok":
                bid_qty = float(ob_data.get("bid_qty") or 0.0)
                ask_qty = float(ob_data.get("ask_qty") or 0.0)

        # O(1) 상태 갱신
        state.update_poll(
            price=price,
            buy_vol_total=buy_vol_total,
            sell_vol_total=sell_vol_total,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
        )

        # 포지션 보유 여부 및 미실현 손익
        pos = position_info.get(symbol)
        in_position = pos is not None
        unrealized_pnl = 0.0
        if in_position and price > 0 and pos.get("entry_price", 0) > 0:
            unrealized_pnl = (price - pos["entry_price"]) / pos["entry_price"]

        # O(1) 신호 평가
        sig: OrderFlowSignal = state.evaluate(
            in_position=in_position,
            unrealized_pnl=unrealized_pnl,
        )

        return {
            "symbol": symbol,
            "action": sig.action,
            "reason": sig.reason,
            "exec_strength": round(sig.exec_strength, 1),
            "ob_imbalance": round(sig.ob_imbalance, 3),
            "vol_ratio": round(sig.vol_ratio, 2),
            "price": price,
            "unrealized_pnl": round(unrealized_pnl, 4),
            "in_position": in_position,
        }

    def _public(self, task_id: str) -> dict[str, Any]:
        task = self._tasks[task_id]
        return {"status": "ok", "task": self._strip(task)}

    def _strip(self, task: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in task.items() if not k.startswith("_")}


# 싱글턴
_runner = KROrderFlowRunner()


def get_runner() -> KROrderFlowRunner:
    return _runner
