from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FakeOrderbook:
    bid1: float
    ask1: float
    bid_qty: int = 10_000
    ask_qty: int = 10_000
    age_sec: float = 0.2
    depth_levels: int = 5

    def depth_fields(self) -> dict:
        fields = {
            "bid_qty": self.bid_qty,
            "ask_qty": self.ask_qty,
            "bid1_price": self.bid1,
            "ask1_price": self.ask1,
            "bid1_qty": self.bid_qty,
            "ask1_qty": self.ask_qty,
            "orderbook_age_sec": self.age_sec,
            "depth_levels_available": self.depth_levels,
            "orderbook_stale": self.age_sec > 3.0,
            "orderbook_quality": "fresh" if self.age_sec <= 1.0 else "degraded",
        }
        for i in range(2, 11):
            fields[f"bid{i}_price"] = max(1.0, self.bid1 - (i - 1) * 10)
            fields[f"ask{i}_price"] = self.ask1 + (i - 1) * 10
            fields[f"bid{i}_qty"] = max(0, self.bid_qty - (i - 1) * 100)
            fields[f"ask{i}_qty"] = max(0, self.ask_qty - (i - 1) * 100)
        return fields

