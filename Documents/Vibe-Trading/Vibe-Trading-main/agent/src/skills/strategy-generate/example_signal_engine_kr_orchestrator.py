"""KR orchestrator example: opening-strength cross-sectional ranking.

Designed for multi-symbol Korea-market workflows where the orchestrator needs
`artifacts/symbol_scores.json` to decide final trade targets.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

from src.trading.signal_ranking_artifact import export_latest_signal_scores


class SignalEngine:
    """Rank KR symbols by opening strength and keep the top N names."""

    def __init__(
        self,
        lookback_bars: int = 3,
        top_n: int = 2,
    ) -> None:
        self.lookback_bars = lookback_bars
        self.top_n = top_n

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        if not data_map:
            return {}

        codes = list(data_map.keys())
        common_index = self._build_common_index(data_map)
        if common_index.empty:
            return {code: pd.Series(0.0, index=df.index) for code, df in data_map.items()}

        cross_sectional = {code: pd.Series(0.0, index=common_index) for code in codes}

        for timestamp in common_index:
            scored = []
            for code, df in data_map.items():
                if timestamp not in df.index:
                    continue
                window = df.loc[:timestamp].tail(self.lookback_bars)
                score = self._compute_opening_strength(window)
                if score is None:
                    continue
                scored.append((code, score))

            if not scored:
                continue

            scored.sort(key=lambda item: item[1], reverse=True)
            selected = [code for code, _ in scored[: min(self.top_n, len(scored))]]
            weight = 1.0 / len(selected) if selected else 0.0
            for code in selected:
                cross_sectional[code].at[timestamp] = weight

        result: Dict[str, pd.Series] = {}
        for code, df in data_map.items():
            result[code] = cross_sectional[code].reindex(df.index).fillna(0.0)

        export_latest_signal_scores(
            result,
            metadata={"selection_reason": "kr opening strength rank"},
        )
        return result

    def _compute_opening_strength(self, window: pd.DataFrame) -> float | None:
        if len(window) < self.lookback_bars:
            return None
        required = {"open", "close", "high", "low", "volume"}
        if not required.issubset(window.columns):
            return None

        first_open = float(window["open"].iloc[0])
        last_close = float(window["close"].iloc[-1])
        session_high = float(window["high"].max())
        session_low = float(window["low"].min())
        total_volume = float(window["volume"].sum())
        if first_open <= 0 or session_high <= 0 or total_volume <= 0:
            return None

        return_pct = (last_close / first_open) - 1.0
        range_pct = (session_high / max(session_low, 1e-12)) - 1.0
        volume_score = total_volume / len(window)
        return (return_pct * 100.0) + (range_pct * 10.0) + (volume_score / 1_000_000.0)

    @staticmethod
    def _build_common_index(data_map: Dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
        indexes = [df.index for df in data_map.values() if not df.empty]
        if not indexes:
            return pd.DatetimeIndex([])
        common = indexes[0]
        for idx in indexes[1:]:
            common = common.intersection(idx)
        return pd.DatetimeIndex(common)
