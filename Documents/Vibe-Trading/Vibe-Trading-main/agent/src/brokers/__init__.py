"""Broker adapter registry."""

from __future__ import annotations

from src.brokers.base import BrokerAdapter, BrokerExecutionResult, BrokerOrderRequest
from src.brokers.kis import KISBrokerAdapter
from src.brokers.kiwoom import KiwoomBrokerAdapter


BROKER_REGISTRY = {
    KISBrokerAdapter.name: KISBrokerAdapter,
    KiwoomBrokerAdapter.name: KiwoomBrokerAdapter,
}


def get_broker_adapter(name: str) -> BrokerAdapter:
    normalized = str(name or "").strip().lower()
    adapter_cls = BROKER_REGISTRY.get(normalized)
    if adapter_cls is None:
        raise ValueError(f"Unsupported broker: {name}")
    return adapter_cls.from_env()


__all__ = [
    "BrokerAdapter",
    "BrokerExecutionResult",
    "BrokerOrderRequest",
    "KISBrokerAdapter",
    "KiwoomBrokerAdapter",
    "BROKER_REGISTRY",
    "get_broker_adapter",
]
