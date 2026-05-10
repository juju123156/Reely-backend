"""StateStore — Redis(실전) / 인메모리(개발) 상태 저장."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 공통 인터페이스 ────────────────────────────────────────────────────────────

class BaseStateStore:
    async def save_position(self, symbol: str, data: dict, ttl: Optional[int] = None) -> None: ...
    async def load_positions(self) -> dict[str, dict]: ...
    async def delete_position(self, symbol: str) -> None: ...
    async def save_risk(self, data: dict) -> None: ...
    async def load_risk(self) -> Optional[dict]: ...
    async def log_trade(self, trade: dict) -> None: ...
    async def get_trades_today(self) -> list[dict]: ...
    async def close(self) -> None: ...


# ── 인메모리 구현 (Redis 없을 때 기본값) ───────────────────────────────────────

class InMemoryStateStore(BaseStateStore):
    """
    개발/테스트용. 프로세스 재시작 시 상태 유실.
    장 시작 시 bot.py에서 inquire_balance()로 포지션 재확인 필요.
    """

    def __init__(self) -> None:
        self._positions: dict[str, dict] = {}
        self._risk: Optional[dict] = None
        self._trades: list[dict] = []

    async def save_position(self, symbol: str, data: dict, ttl: Optional[int] = None) -> None:
        self._positions[symbol] = data

    async def load_positions(self) -> dict[str, dict]:
        return dict(self._positions)

    async def delete_position(self, symbol: str) -> None:
        self._positions.pop(symbol, None)

    async def save_risk(self, data: dict) -> None:
        self._risk = data

    async def load_risk(self) -> Optional[dict]:
        return self._risk

    async def log_trade(self, trade: dict) -> None:
        self._trades.append({**trade, "_logged_at": time.time()})
        logger.info(
            "Trade log: %s %s qty=%s price=%s pnl=%s reason=%s",
            trade.get("symbol"), trade.get("side"),
            trade.get("filled_qty"), trade.get("fill_price"),
            trade.get("net_pnl"), trade.get("reason"),
        )

    async def get_trades_today(self) -> list[dict]:
        return list(self._trades)

    async def close(self) -> None:
        pass


# ── Redis 구현 (실전) ──────────────────────────────────────────────────────────

class RedisStateStore(BaseStateStore):
    """
    Redis 키 설계:
      scalping:positions:{symbol}   → JSON  TTL: 당일 자정
      scalping:risk:daily           → JSON  TTL: 당일 자정
      scalping:trades:{date}        → LIST  TTL: 7일

    실전 주의:
    - Redis 장애 시 포지션 정보 유실 → PostgreSQL 최신 기록으로 복구 필요
    - TTL은 장 종료(15:30) 이후 자정까지로 설정 (~8시간)
    - 연결 실패 시 InMemoryStateStore로 자동 fallback
    """

    _TTL_SECONDS = 8 * 3600   # 8시간

    def __init__(self, host: str = "localhost", port: int = 6379,
                 db: int = 0, password: str = "") -> None:
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._redis: Any = None

    async def connect(self) -> bool:
        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(
                f"redis://{self._host}:{self._port}/{self._db}",
                password=self._password or None,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("Redis connected: %s:%d", self._host, self._port)
            return True
        except Exception as exc:
            logger.warning("Redis connect failed: %s — fallback to InMemory", exc)
            return False

    async def save_position(self, symbol: str, data: dict, ttl: Optional[int] = None) -> None:
        if not self._redis:
            return
        key = f"scalping:positions:{symbol}"
        effective_ttl = ttl if ttl is not None else self._TTL_SECONDS
        await self._redis.set(key, json.dumps(data), ex=effective_ttl)

    async def load_positions(self) -> dict[str, dict]:
        if not self._redis:
            return {}
        result = {}
        try:
            keys = await self._redis.keys("scalping:positions:*")
            for key in keys:
                symbol = key.split(":")[-1]
                raw = await self._redis.get(key)
                if raw:
                    result[symbol] = json.loads(raw)
        except Exception as exc:
            logger.warning("load_positions error: %s", exc)
        return result

    async def delete_position(self, symbol: str) -> None:
        if not self._redis:
            return
        await self._redis.delete(f"scalping:positions:{symbol}")

    async def save_risk(self, data: dict) -> None:
        if not self._redis:
            return
        await self._redis.set("scalping:risk:daily", json.dumps(data), ex=self._TTL_SECONDS)

    async def load_risk(self) -> Optional[dict]:
        if not self._redis:
            return None
        raw = await self._redis.get("scalping:risk:daily")
        return json.loads(raw) if raw else None

    async def log_trade(self, trade: dict) -> None:
        if not self._redis:
            logger.info("Trade (no Redis): %s", trade)
            return
        from datetime import date
        key = f"scalping:trades:{date.today().isoformat()}"
        await self._redis.rpush(key, json.dumps(trade))
        await self._redis.expire(key, 7 * 24 * 3600)

    async def get_trades_today(self) -> list[dict]:
        if not self._redis:
            return []
        from datetime import date
        key = f"scalping:trades:{date.today().isoformat()}"
        raws = await self._redis.lrange(key, 0, -1)
        return [json.loads(r) for r in raws]

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()


# ── 팩토리 ───────────────────────────────────────────────────────────────────

async def make_state_store(cfg) -> BaseStateStore:
    """설정에 따라 Redis 또는 InMemory 스토어 반환."""
    redis_cfg = getattr(cfg, "redis", None)
    if redis_cfg and getattr(redis_cfg, "enabled", False):
        store = RedisStateStore(
            host=redis_cfg.host,
            port=redis_cfg.port,
            db=redis_cfg.db,
            password=redis_cfg.password,
        )
        ok = await store.connect()
        if ok:
            return store
        logger.warning("Falling back to InMemoryStateStore")
    return InMemoryStateStore()
