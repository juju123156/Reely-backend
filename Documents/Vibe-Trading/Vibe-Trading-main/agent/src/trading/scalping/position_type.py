"""PositionType — 포지션 목적 분류 enum + 복구 헬퍼."""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Optional


class PositionType(Enum):
    INTRADAY_SCALP = "intraday_scalp"   # 09:00~10:30, 당일 청산 강제
    LUNCH_REBOUND  = "lunch_rebound"    # 11:30~13:30, 당일 청산 강제
    CLOSE_BET      = "close_bet"        # 14:50~15:15, 익일 오전 청산
    UNKNOWN        = "unknown"          # 복구 실패 — 신규 진입 금지, 보수적 청산


# ── 포지션 타입별 Redis TTL ────────────────────────────────────────────────────

_TTL_MAP: dict[PositionType, int] = {
    PositionType.INTRADAY_SCALP: 8 * 3600,   # 당일 자정 전 만료
    PositionType.LUNCH_REBOUND:  8 * 3600,
    PositionType.CLOSE_BET:     30 * 3600,   # 익일 11:00까지 생존 (14:50 진입 기준)
    PositionType.UNKNOWN:        8 * 3600,
}


def ttl_for(pt: PositionType) -> int:
    """포지션 타입별 Redis TTL(초) 반환."""
    return _TTL_MAP.get(pt, 8 * 3600)


def from_value(value: Optional[str]) -> PositionType:
    """문자열에서 PositionType 복원. 실패 시 UNKNOWN."""
    if not value:
        return PositionType.UNKNOWN
    try:
        return PositionType(value)
    except ValueError:
        return PositionType.UNKNOWN


# ── broker-only 복구 시 타입 추론 ────────────────────────────────────────────

_MARKET_OPEN = time(9, 0)
_PREMARKET_THRESHOLD = time(9, 10)   # 9:10 이전 = 전날 종가베팅 가능성 높음


def infer_from_recovery_time(
    now: Optional[datetime] = None,
) -> tuple[PositionType, str, str]:
    """
    Redis에 없고 broker 잔고에만 존재하는 포지션의 타입 추론.

    반환: (position_type, entry_session, intended_exit_session)

    규칙:
      - 09:10 이전 → CLOSE_BET (전날 종가베팅 가능성 높음)
      - 09:10 이후 → UNKNOWN  (타입 불확실, 보수적 처리)
    """
    t = (now or datetime.now()).time()
    if t < _PREMARKET_THRESHOLD:
        return PositionType.CLOSE_BET, "broker_recovered", "next_open"
    return PositionType.UNKNOWN, "broker_recovered", "manual"


def intended_exit_for(pt: PositionType) -> str:
    """포지션 타입별 기본 청산 세션."""
    return "next_open" if pt == PositionType.CLOSE_BET else "same_day"
