"""Broker adapter interfaces for market data and execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BrokerOrderRequest:
    symbol: str
    side: str
    qty_policy: str
    limit_policy: str = ""
    time_in_force: str = "DAY"
    quantity: float | None = None
    limit_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerExecutionResult:
    broker: str
    mode: str
    status: str
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    message: str = ""
    accepted: bool = False
    dry_run: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BrokerAdapter(ABC):
    """Abstract broker adapter."""

    name: str = ""
    supports_live: bool = False
    supports_paper: bool = True

    @classmethod
    @abstractmethod
    def from_env(cls) -> "BrokerAdapter":
        """Create adapter from environment configuration."""

    @abstractmethod
    def check_connection(self) -> dict[str, Any]:
        """Return connection/credential readiness."""

    @abstractmethod
    def place_order(
        self,
        order: BrokerOrderRequest,
        *,
        mode: str,
        dry_run: bool,
    ) -> BrokerExecutionResult:
        """Submit or simulate one order."""

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return {"status": "error", "error": "cancel_order not implemented", "order_id": order_id}

    def get_orders(self) -> dict[str, Any]:
        return {"status": "error", "error": "get_orders not implemented"}

    def get_fills(self) -> dict[str, Any]:
        return {"status": "error", "error": "get_fills not implemented"}

    def get_positions(self) -> dict[str, Any]:
        return {"status": "error", "error": "get_positions not implemented"}

    def get_quote(self, symbol: str) -> dict[str, Any]:
        return {"status": "error", "error": "get_quote not implemented", "symbol": symbol}

    def get_intraday_bars(self, symbol: str, interval: str, start: str, end: str) -> dict[str, Any]:
        return {
            "status": "error",
            "error": "get_intraday_bars not implemented",
            "symbol": symbol,
            "interval": interval,
            "start": start,
            "end": end,
        }
