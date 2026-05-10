"""Leader rotation scoring for Korean intraday momentum candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LeaderProfile:
    symbol: str
    leader_rank: int
    leader_score: float
    turnover_rank: int
    reason: str


class LeaderRotationEngine:
    """Ranks candidates so true leaders can use faster entry rules.

    This intentionally stays data-light: turnover, change persistence, execution
    strength, and liquidity are available from the scanner without adding a new
    API dependency. Theme/news enrichment can be layered on later.
    """

    def rank(self, candidates: Iterable) -> dict[str, LeaderProfile]:
        items = [c for c in candidates if getattr(c, "trading_value", 0.0) > 0]
        if not items:
            return {}

        by_turnover = sorted(items, key=lambda c: getattr(c, "trading_value", 0.0), reverse=True)
        max_turnover = max(float(getattr(by_turnover[0], "trading_value", 0.0)), 1.0)
        profiles: list[LeaderProfile] = []
        for idx, c in enumerate(by_turnover, start=1):
            turnover_ratio = min(float(getattr(c, "trading_value", 0.0)) / max_turnover, 1.0)
            change_pct = max(0.0, min(float(getattr(c, "change_pct", 0.0)) / 0.12, 1.0))
            exec_strength = max(0.0, min(float(getattr(c, "exec_strength", 0.0)) / 150.0, 1.0))
            vol_ratio = max(0.0, min(float(getattr(c, "vol_ratio", 0.0)) / 3.0, 1.0))
            score = (
                turnover_ratio * 45.0
                + change_pct * 25.0
                + exec_strength * 20.0
                + vol_ratio * 10.0
            )
            profiles.append(
                LeaderProfile(
                    symbol=str(getattr(c, "symbol", "")),
                    leader_rank=idx,
                    leader_score=round(score, 1),
                    turnover_rank=idx,
                    reason=(
                        f"turnover_rank={idx} turnover_ratio={turnover_ratio:.2f} "
                        f"change={change_pct:.2f} exec={exec_strength:.2f} vol={vol_ratio:.2f}"
                    ),
                )
            )

        by_score = sorted(profiles, key=lambda p: p.leader_score, reverse=True)
        return {
            p.symbol: LeaderProfile(
                symbol=p.symbol,
                leader_rank=rank,
                leader_score=p.leader_score,
                turnover_rank=p.turnover_rank,
                reason=p.reason,
            )
            for rank, p in enumerate(by_score, start=1)
        }
