"""Background realtime broker runner for selection updates."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.brokers import get_broker_adapter
from src.tools.path_utils import safe_path as _safe_path
from src.trading.realtime_selection import apply_realtime_selection_update


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RealtimeBrokerRunnerManager:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        broker_name: str,
        run_dir: str,
        path: str,
        symbols: list[str],
        market_code: str = "KRX",
        quote_types: list[str] | None = None,
        score_field: str = "flu_rt",
        max_positions: int | None = None,
        selection_reason: str = "",
        poll_interval: float = 5.0,
        env_dv: str | None = None,
        max_cycles: int | None = None,
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:8]
        stop_event = threading.Event()
        task = {
            "task_id": task_id,
            "status": "running",
            "broker_name": broker_name,
            "run_dir": run_dir,
            "path": path,
            "symbols": list(symbols),
            "market_code": market_code,
            "score_field": score_field,
            "max_positions": max_positions,
            "selection_reason": selection_reason,
            "poll_interval": poll_interval,
            "env_dv": env_dv or "",
            "max_cycles": max_cycles,
            "iterations": 0,
            "last_result": {},
            "last_error": "",
            "updated_at": _now_iso(),
            "_stop_event": stop_event,
        }
        with self._lock:
            self.tasks[task_id] = task
        thread = threading.Thread(
            target=self._run_loop,
            args=(task_id, quote_types or ["0B"]),
            daemon=True,
        )
        task["_thread"] = thread
        thread.start()
        return self._public_task(task_id)

    def stop(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return {"status": "error", "error": f"unknown realtime runner: {task_id}"}
            task["_stop_event"].set()
            task["status"] = "stopping"
            task["updated_at"] = _now_iso()
        return self._public_task(task_id)

    def status(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if task_id:
                task = self.tasks.get(task_id)
                if not task:
                    return {"status": "error", "error": f"unknown realtime runner: {task_id}"}
                return self._public_task(task_id)
            return {
                "status": "ok",
                "tasks": [self._strip_private(task) for task in self.tasks.values()],
            }

    def _public_task(self, task_id: str) -> dict[str, Any]:
        task = self.tasks[task_id]
        return {"status": "ok", "task": self._strip_private(task)}

    def _strip_private(self, task: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in task.items() if not k.startswith("_")}

    def _run_loop(self, task_id: str, quote_types: list[str]) -> None:
        while True:
            with self._lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                if task["_stop_event"].is_set():
                    task["status"] = "stopped"
                    task["updated_at"] = _now_iso()
                    return
                task["updated_at"] = _now_iso()
                broker_name = str(task["broker_name"])
                run_dir = str(task["run_dir"])
                path = str(task["path"])
                symbols = list(task["symbols"])
                market_code = str(task["market_code"])
                score_field = str(task["score_field"])
                max_positions = task["max_positions"]
                selection_reason = str(task["selection_reason"])
                poll_interval = float(task["poll_interval"])
                env_dv = task["env_dv"] or None
                max_cycles = task["max_cycles"]
                iterations = int(task["iterations"])

            try:
                adapter = get_broker_adapter(broker_name)
                request = adapter.build_quote_subscription(
                    symbols,
                    quote_types=quote_types,
                    market_code=market_code,
                )
                ws_result = adapter.run_websocket_roundtrip(
                    [request],
                    env_dv=env_dv,
                    receive_count=1,
                    timeout=max(1.0, poll_interval),
                )
                self._write_message_snapshot(run_dir, ws_result)
                if ws_result.get("status") != "ok":
                    self._update_task(task_id, status="error", last_error=ws_result.get("error") or "websocket roundtrip failed", last_result=ws_result)
                    return
                selection_result = apply_realtime_selection_update(
                    path,
                    run_dir=run_dir,
                    messages=ws_result.get("messages") or [],
                    score_field=score_field,
                    max_positions=max_positions,
                    selection_reason=selection_reason or "broker realtime quote update",
                )
                self._update_task(
                    task_id,
                    status="running",
                    last_error="" if selection_result.get("status") == "ok" else str(selection_result.get("error") or ""),
                    last_result={
                        "websocket": ws_result,
                        "selection": selection_result,
                    },
                    iterations=iterations + 1,
                )
                if max_cycles is not None and iterations + 1 >= int(max_cycles):
                    self._update_task(task_id, status="completed")
                    return
            except Exception as exc:
                self._update_task(task_id, status="error", last_error=str(exc))
                return

            if task["_stop_event"].wait(poll_interval):
                self._update_task(task_id, status="stopped")
                return

    def _update_task(self, task_id: str, **updates: Any) -> None:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.update(updates)
            task["updated_at"] = _now_iso()

    def _write_message_snapshot(self, run_dir: str, payload: dict[str, Any]) -> None:
        artifacts_dir = Path(run_dir) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        target = _safe_path("artifacts/realtime_broker_messages.json", Path(run_dir))
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_RUNNER = RealtimeBrokerRunnerManager()


def get_realtime_runner_manager() -> RealtimeBrokerRunnerManager:
    return _RUNNER
