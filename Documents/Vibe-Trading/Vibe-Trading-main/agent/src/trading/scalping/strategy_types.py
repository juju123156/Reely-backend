"""Common strategy routing types for intraday scalping."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .position_type import PositionType


class StrategyMode(Enum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    LIVE = "live"


class StrategyName(Enum):
    OPENING_MOMENTUM = "opening_momentum"
    SHALLOW_PULLBACK = "shallow_pullback"
    VWAP_RECLAIM = "vwap_reclaim"
    MOMENTUM_CONTINUATION = "momentum_continuation"
    LEADER_ROTATION = "leader_rotation"
    DEEP_PULLBACK = "deep_pullback"
    CLOSE_BET = "close_bet"
    CURRENT_STRATEGY = "current_strategy"


@dataclass(frozen=True)
class StrategySignal:
    strategy_name: str
    symbol: str
    side: Literal["buy", "sell"]
    confidence: float
    expected_edge_pct: float
    entry_price: float | None
    stop_price: float | None
    take_profit_price: float | None
    position_type: PositionType
    live_allowed: bool
    shadow_only: bool
    reason: str
    metrics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyCandidate:
    strategy_name: str
    symbol: str
    mode: StrategyMode
    priority: int
    reason: str
    metrics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyActivation:
    name: StrategyName
    mode: StrategyMode
    reason: str


@dataclass(frozen=True)
class StrategyContext:
    now_time: object
    regime: str = ""
    market_ok: bool = True
    cost_floor_pct: float = 0.004
    candidate: object | None = None
    signal_snapshot: dict = field(default_factory=dict)
    symbol_state: object | None = None
