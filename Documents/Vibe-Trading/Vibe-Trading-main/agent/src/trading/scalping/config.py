"""스캘핑 봇 설정 — Pydantic v2 + pydantic-settings."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    ATR_STOP_MULTIPLIER, ATR_TRAIL_MULTIPLIER,
    DAILY_LOSS_LIMIT_PCT, MAX_CONSECUTIVE_LOSSES,
    MAX_SYMBOLS, MAX_POSITION_PCT,
    PARTIAL_EXIT_1_PCT, PARTIAL_EXIT_2_PCT,
    MIN_ENTRY_SCORE,
)


class BrokerConfig(BaseModel):
    name: str = "kis"
    env: str = "demo"           # "demo" | "real"
    account_no: str = ""
    product_code: str = "01"


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    enabled: bool = False       # 기본 비활성 (인메모리 대체)


class DBConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///./scalping_trades.db"
    enabled: bool = False       # 기본 비활성 (로그만)


class NotifierConfig(BaseModel):
    discord_webhook: str = ""
    slack_webhook: str = ""
    enabled: bool = False


class StrategyConfig(BaseModel):
    min_entry_score: float = MIN_ENTRY_SCORE
    max_symbols: int = MAX_SYMBOLS
    daily_loss_limit: float = DAILY_LOSS_LIMIT_PCT
    max_consecutive_losses: int = MAX_CONSECUTIVE_LOSSES
    max_position_pct: float = MAX_POSITION_PCT
    atr_stop_mult: float = ATR_STOP_MULTIPLIER
    atr_trail_mult: float = ATR_TRAIL_MULTIPLIER
    partial_exit_1_pct: float = PARTIAL_EXIT_1_PCT
    partial_exit_2_pct: float = PARTIAL_EXIT_2_PCT
    dry_run: bool = True        # True = 모의투자 (주문 실행 안 함)
    dry_run_order: bool = False # True = 주문 API 직전까지 실행하고 전송만 차단


class ScalpingBotConfig(BaseSettings):
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    db: DBConfig = Field(default_factory=DBConfig)
    notifier: NotifierConfig = Field(default_factory=NotifierConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env.paper",
        env_nested_delimiter="__",
        extra="ignore",
    )
