"""Macro overnight feed adapters and quality grading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Any


@dataclass(frozen=True)
class MacroOvernightSnapshot:
    nasdaq_futures_pct: float | None = None
    sox_pct: float | None = None
    nvda_pct: float | None = None
    usdkrw_pct: float | None = None
    korea_night_futures_pct: float | None = None
    sector_us_proxy_pct: float | None = None
    data_quality: str = "missing"  # full | partial | missing
    missing_fields: list[str] = field(default_factory=list)
    ts: datetime = field(default_factory=datetime.now)


class MacroFeedAdapter(Protocol):
    def fetch(self) -> dict[str, Any]:
        ...


class ManualMacroAdapter:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data or {}

    def fetch(self) -> dict[str, Any]:
        return dict(self._data)


class MacroOvernightFeedEngine:
    REQUIRED = ("nasdaq_futures_pct", "usdkrw_pct", "korea_night_futures_pct")
    OPTIONAL = ("sox_pct", "nvda_pct", "sector_us_proxy_pct")

    def __init__(self, adapters: list[MacroFeedAdapter] | None = None) -> None:
        self._adapters = adapters or []
        self._last_snapshot = MacroOvernightSnapshot()

    def snapshot(self) -> MacroOvernightSnapshot:
        merged: dict[str, Any] = {}
        for adapter in self._adapters:
            try:
                raw = adapter.fetch()
                for key, value in raw.items():
                    if value is not None and key not in merged:
                        merged[key] = value
            except Exception:
                continue
        snapshot = self._build_snapshot(merged)
        self._last_snapshot = snapshot
        return snapshot

    @classmethod
    def _build_snapshot(cls, data: dict[str, Any]) -> MacroOvernightSnapshot:
        missing = [key for key in (*cls.REQUIRED, *cls.OPTIONAL) if data.get(key) is None]
        required_present = sum(1 for key in cls.REQUIRED if data.get(key) is not None)
        optional_present = sum(1 for key in cls.OPTIONAL if data.get(key) is not None)
        if required_present == len(cls.REQUIRED) and optional_present >= 2:
            quality = "full"
        elif required_present > 0:
            quality = "partial"
        else:
            quality = "missing"
        return MacroOvernightSnapshot(
            nasdaq_futures_pct=_maybe_float(data.get("nasdaq_futures_pct")),
            sox_pct=_maybe_float(data.get("sox_pct")),
            nvda_pct=_maybe_float(data.get("nvda_pct")),
            usdkrw_pct=_maybe_float(data.get("usdkrw_pct")),
            korea_night_futures_pct=_maybe_float(data.get("korea_night_futures_pct")),
            sector_us_proxy_pct=_maybe_float(data.get("sector_us_proxy_pct")),
            data_quality=quality,
            missing_fields=missing,
        )


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
