"""Runtime strategy parameter overrides from JSON/YAML config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import (
    LEADER_MIN_SCORE,
    LEADER_SHADOW_MIN_SCORE,
    MOMENTUM_CONTINUATION_MAX_PULLBACK_PCT,
    MOMENTUM_CONTINUATION_MAX_SPREAD_PCT,
    MOMENTUM_CONTINUATION_MIN_EXEC,
    MOMENTUM_CONTINUATION_MIN_VOL_RATIO,
    SHALLOW_ENTRY_EXEC_MIN,
    SHALLOW_ENTRY_OB_MIN,
    SHALLOW_ENTRY_SCORE,
    SHALLOW_ENTRY_VWAP_MIN_GAP,
    SHALLOW_PULLBACK_MIN_PCT,
)


DEFAULT_STRATEGY_PARAMS: dict[str, dict[str, Any]] = {
    "leader_rotation": {
        "leader_min_score": LEADER_MIN_SCORE,
        "leader_shadow_min_score": LEADER_SHADOW_MIN_SCORE,
    },
    "shallow_pullback": {
        "pullback_min_pct": SHALLOW_PULLBACK_MIN_PCT,
        "pullback_max_pct": 0.012,
        "entry_exec_min": SHALLOW_ENTRY_EXEC_MIN,
        "entry_ob_min": SHALLOW_ENTRY_OB_MIN,
        "entry_vwap_min_gap": SHALLOW_ENTRY_VWAP_MIN_GAP,
        "entry_score": SHALLOW_ENTRY_SCORE,
        "max_spread_pct": 0.003,
    },
    "vwap_reclaim": {
        "min_change_pct": 0.03,
        "min_exec_strength": 105.0,
        "min_vol_ratio": 1.5,
        "min_vwap_gap": 0.0,
        "max_spread_pct": 0.0025,
    },
    "momentum_continuation": {
        "max_pullback_pct": MOMENTUM_CONTINUATION_MAX_PULLBACK_PCT,
        "min_exec_strength": MOMENTUM_CONTINUATION_MIN_EXEC,
        "min_vol_ratio": MOMENTUM_CONTINUATION_MIN_VOL_RATIO,
        "max_spread_pct": MOMENTUM_CONTINUATION_MAX_SPREAD_PCT,
    },
    "exit": {
        "fast_take_profit_pct": 0.010,
        "fast_time_stop_secs": 300,
        "fast_trailing_pct": 0.010,
    },
    "promotion": {
        "leader_shallow_min_samples": 50,
        "vwap_reclaim_min_samples": 50,
        "momentum_continuation_min_samples": 100,
    },
}


class StrategyParameterStore:
    def __init__(self, path: str | Path = "config/strategies.json") -> None:
        self.path = Path(path)
        self._params = self._load()

    def section(self, name: str) -> dict[str, Any]:
        merged = dict(DEFAULT_STRATEGY_PARAMS.get(name, {}))
        merged.update(self._params.get(name, {}))
        return merged

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.section(section).get(key, default)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            text = self.path.read_text(encoding="utf-8")
            if self.path.suffix.lower() in {".yaml", ".yml"}:
                try:
                    import yaml  # type: ignore
                except Exception:
                    return {}
                loaded = yaml.safe_load(text) or {}
            else:
                loaded = json.loads(text)
        except Exception:
            return {}
        if not isinstance(loaded, dict):
            return {}
        return {
            str(k): v
            for k, v in loaded.items()
            if isinstance(v, dict)
        }
