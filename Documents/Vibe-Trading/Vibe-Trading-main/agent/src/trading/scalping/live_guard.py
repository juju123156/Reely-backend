"""Operational kill-switch guard for live intraday execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LiveGuardConfig:
    stale_tick_sec: float = 5.0
    stale_tick_repeats: int = 3
    order_timeout_limit: int = 3
    slippage_limit_pct: float = 0.003
    slippage_repeats: int = 2
    api_error_limit: int = 3
    fill_missing_limit: int = 3


@dataclass
class LiveGuardState:
    stale_tick_repeats: int = 0
    order_timeouts: int = 0
    slippage_exceeds: int = 0
    api_errors: int = 0
    missing_fills: int = 0
    last_reason: str = ""
    history: list[str] = field(default_factory=list)


class LiveKillSwitchGuard:
    def __init__(self, config: LiveGuardConfig | None = None) -> None:
        self.config = config or LiveGuardConfig()
        self.state = LiveGuardState()

    def observe_tick_age(self, age_sec: float) -> str:
        if age_sec >= self.config.stale_tick_sec:
            self.state.stale_tick_repeats += 1
            return self._trip_if(
                self.state.stale_tick_repeats >= self.config.stale_tick_repeats,
                "tick_stale_repeated",
            )
        self.state.stale_tick_repeats = 0
        return ""

    def observe_order_timeout(self) -> str:
        self.state.order_timeouts += 1
        return self._trip_if(
            self.state.order_timeouts >= self.config.order_timeout_limit,
            "order_timeout_repeated",
        )

    def observe_slippage(self, slippage_pct: float) -> str:
        if slippage_pct > self.config.slippage_limit_pct:
            self.state.slippage_exceeds += 1
            return self._trip_if(
                self.state.slippage_exceeds >= self.config.slippage_repeats,
                "slippage_exceeded_repeated",
            )
        self.state.slippage_exceeds = 0
        return ""

    def observe_api_error(self) -> str:
        self.state.api_errors += 1
        return self._trip_if(
            self.state.api_errors >= self.config.api_error_limit,
            "api_error_repeated",
        )

    def observe_missing_fill(self) -> str:
        self.state.missing_fills += 1
        return self._trip_if(
            self.state.missing_fills >= self.config.fill_missing_limit,
            "fill_notification_missing_repeated",
        )

    def reset_order_health(self) -> None:
        self.state.order_timeouts = 0
        self.state.missing_fills = 0

    def _trip_if(self, condition: bool, reason: str) -> str:
        if not condition:
            return ""
        self.state.last_reason = reason
        self.state.history.append(reason)
        return reason
