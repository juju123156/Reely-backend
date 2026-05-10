"""Leader rotation policy layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import LEADER_RANK_MAX, LEADER_MIN_SCORE, LEADER_SHADOW_MIN_SCORE


@dataclass(frozen=True)
class LeaderContext:
    symbol: str
    leader_rank: int
    theme: str | None
    theme_strength: float
    trading_value_rank: int
    is_leader: bool
    is_follower: bool
    leader_score: float
    allow_opening_momentum: bool
    allow_shallow_pullback: bool
    allow_leader_shadow: bool
    allow_deep_pullback: bool
    position_size_multiplier: float
    reason: str


class LeaderRotationStrategy:
    """Turns scanner leader scores into policy decisions."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = params or {}

    def build_context(self, candidate: Any | None) -> LeaderContext:
        if candidate is None:
            return LeaderContext(
                symbol="",
                leader_rank=999,
                theme=None,
                theme_strength=0.0,
                trading_value_rank=999,
                is_leader=False,
                is_follower=True,
                leader_score=0.0,
                allow_opening_momentum=False,
                allow_shallow_pullback=False,
                allow_leader_shadow=False,
                allow_deep_pullback=True,
                position_size_multiplier=0.5,
                reason="no_candidate",
            )

        symbol = str(getattr(candidate, "symbol", ""))
        leader_rank = int(getattr(candidate, "leader_rank", 999) or 999)
        leader_score = float(getattr(candidate, "leader_score", 0.0) or 0.0)
        is_etf_like = bool(
            getattr(candidate, "is_etf", False)
            or getattr(candidate, "is_etn", False)
            or getattr(candidate, "is_spac", False)
        )
        leader_min_score = float(self._params.get("leader_min_score", LEADER_MIN_SCORE))
        leader_shadow_min_score = float(self._params.get("leader_shadow_min_score", LEADER_SHADOW_MIN_SCORE))
        is_leader = (
            not is_etf_like
            and leader_rank <= LEADER_RANK_MAX
            and leader_score >= leader_min_score
        )
        allow_leader_shadow = (
            not is_etf_like
            and leader_rank <= LEADER_RANK_MAX
            and leader_score >= leader_shadow_min_score
        )
        reason = "leader" if is_leader else "follower"
        if allow_leader_shadow and not is_leader:
            reason = "leader_score_near_miss"
        if is_etf_like:
            reason = "blocked_etf_like"

        return LeaderContext(
            symbol=symbol,
            leader_rank=leader_rank,
            theme=None,
            theme_strength=0.0,
            trading_value_rank=leader_rank,
            is_leader=is_leader,
            is_follower=not is_leader,
            leader_score=leader_score,
            allow_opening_momentum=is_leader,
            allow_shallow_pullback=is_leader,
            allow_leader_shadow=allow_leader_shadow,
            allow_deep_pullback=not is_etf_like and not is_leader,
            position_size_multiplier=1.0 if is_leader else 0.5,
            reason=reason,
        )
