"""Venue execution quality and slippage accounting."""

from __future__ import annotations

from dataclasses import dataclass, field

from .venue import ExecutionVenue, VenuePolicy


@dataclass(frozen=True)
class ExecutionQualityRecord:
    order_id: str
    symbol: str
    preferred_venue: ExecutionVenue
    actual_venue: ExecutionVenue
    venue_policy: VenuePolicy
    expected_price: float
    fill_price: float
    slippage_pct: float
    spread_bps: float = 0.0
    latency_ms: float = 0.0
    routing_result: str = ""
    reason_codes: list[str] = field(default_factory=list)


class VenueSlippageModel:
    def expected_slippage_bps(
        self,
        *,
        venue: ExecutionVenue,
        spread_bps: float,
        urgency: float = 0.0,
        liquidity_penalty: float = 0.0,
        gap_open_impact: float = 0.0,
    ) -> float:
        base = max(0.0, spread_bps) * 0.5
        venue_penalty = 8.0 if venue == ExecutionVenue.NXT else 4.0 if venue == ExecutionVenue.SOR else 2.0
        return base + venue_penalty + max(0.0, urgency) + max(0.0, liquidity_penalty) + max(0.0, gap_open_impact)


class VenueExecutionAnalyzer:
    def __init__(self) -> None:
        self.records: list[ExecutionQualityRecord] = []

    def record(self, record: ExecutionQualityRecord) -> None:
        self.records.append(record)

    def sor_failure_count(self, *, recent: int = 10) -> int:
        rows = self.records[-recent:]
        return sum(
            1
            for row in rows
            if row.venue_policy == VenuePolicy.SOR_BEST_EXECUTION
            and row.routing_result in {"failed", "fallback_krx", "rejected"}
        )

    def unknown_venue_count(self, *, recent: int = 10) -> int:
        return sum(1 for row in self.records[-recent:] if row.actual_venue == ExecutionVenue.UNKNOWN)
