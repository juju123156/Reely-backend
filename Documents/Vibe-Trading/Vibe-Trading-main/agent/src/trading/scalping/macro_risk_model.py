"""Sector-aware macro overnight risk model."""

from __future__ import annotations

from dataclasses import dataclass, field

from .macro_overnight_feed import MacroOvernightSnapshot


SECTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "semiconductor": {
        "nasdaq_futures_pct": 0.20,
        "sox_pct": 0.30,
        "nvda_pct": 0.25,
        "usdkrw_pct": 0.10,
        "korea_night_futures_pct": 0.15,
    },
    "battery": {
        "nasdaq_futures_pct": 0.20,
        "sector_us_proxy_pct": 0.30,
        "usdkrw_pct": 0.15,
        "korea_night_futures_pct": 0.20,
        "sox_pct": 0.05,
        "nvda_pct": 0.10,
    },
    "bio": {
        "nasdaq_futures_pct": 0.30,
        "usdkrw_pct": 0.15,
        "korea_night_futures_pct": 0.25,
        "sector_us_proxy_pct": 0.20,
        "sox_pct": 0.05,
        "nvda_pct": 0.05,
    },
    "default": {
        "nasdaq_futures_pct": 0.30,
        "usdkrw_pct": 0.15,
        "korea_night_futures_pct": 0.30,
        "sector_us_proxy_pct": 0.15,
        "sox_pct": 0.05,
        "nvda_pct": 0.05,
    },
}


@dataclass(frozen=True)
class MacroRiskDecision:
    macro_risk_score: float
    sector: str
    data_quality: str
    reason_codes: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class MacroRiskModel:
    def score(self, snapshot: MacroOvernightSnapshot | None, *, sector: str = "default") -> MacroRiskDecision:
        if snapshot is None:
            snapshot = MacroOvernightSnapshot()
        weights = SECTOR_WEIGHTS.get(sector, SECTOR_WEIGHTS["default"])
        components: dict[str, float] = {}
        weighted = 0.0
        for field, weight in weights.items():
            value = getattr(snapshot, field, None)
            if value is None:
                continue
            if field == "usdkrw_pct":
                component = max(0.0, value) / 0.01 * 100.0
            else:
                component = max(0.0, -value) / 0.02 * 100.0
            component = _clamp(component)
            components[field] = component
            weighted += component * weight
        missing_penalty = 0.0
        reasons: list[str] = []
        if snapshot.data_quality == "partial":
            missing_penalty = 10.0
            reasons.append("macro_data_partial")
        elif snapshot.data_quality == "missing":
            missing_penalty = 25.0
            reasons.append("macro_data_missing")
        score = _clamp(weighted + missing_penalty)
        if score >= 70:
            reasons.append("macro_risk_high")
        elif score >= 50:
            reasons.append("macro_risk_medium")
        return MacroRiskDecision(
            macro_risk_score=score,
            sector=sector,
            data_quality=snapshot.data_quality,
            reason_codes=reasons,
            components={**components, "missing_penalty": missing_penalty},
        )
