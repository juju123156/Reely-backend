"""Explicit market phase state machine for KR intraday scalping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from enum import Enum


class MarketPhase(Enum):
    PRE_OPEN = "PRE_OPEN"
    OPENING_MOMENTUM = "OPENING_MOMENTUM"
    MORNING_SCALP = "MORNING_SCALP"
    MIDDAY_VWAP = "MIDDAY_VWAP"
    LATE_SCALP = "LATE_SCALP"
    CLOSE_BET = "CLOSE_BET"
    AUCTION_LOCKOUT = "AUCTION_LOCKOUT"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class MarketPhaseState:
    phase: MarketPhase
    label: str
    active: bool
    reason: str
    end_at: datetime
    next_phase: MarketPhase
    next_at: datetime


class MarketPhaseResolver:
    def resolve(self, now_dt: datetime) -> MarketPhaseState:
        today = now_dt.date()
        t = now_dt.time()

        def at(tm: dtime) -> datetime:
            return datetime.combine(today, tm)

        def next_day(tm: dtime) -> datetime:
            return datetime.combine(today + timedelta(days=1), tm)

        if t < dtime(9, 0):
            return MarketPhaseState(MarketPhase.PRE_OPEN, "장전", False, "pre_open", at(dtime(9, 5)), MarketPhase.OPENING_MOMENTUM, at(dtime(9, 5)))
        if dtime(9, 0) <= t < dtime(9, 5):
            return MarketPhaseState(MarketPhase.PRE_OPEN, "시초가_대기", False, "opening_lockout", at(dtime(9, 5)), MarketPhase.OPENING_MOMENTUM, at(dtime(9, 5)))
        if dtime(9, 5) <= t < dtime(9, 20):
            return MarketPhaseState(MarketPhase.OPENING_MOMENTUM, "장초_모멘텀", True, "ok", at(dtime(9, 20)), MarketPhase.MORNING_SCALP, at(dtime(9, 20)))
        if dtime(9, 20) <= t < dtime(10, 30):
            return MarketPhaseState(MarketPhase.MORNING_SCALP, "오전_스캘핑", True, "ok", at(dtime(10, 30)), MarketPhase.MIDDAY_VWAP, at(dtime(10, 30)))
        if dtime(10, 30) <= t < dtime(13, 0):
            return MarketPhaseState(MarketPhase.MIDDAY_VWAP, "VWAP_리클레임", True, "ok", at(dtime(13, 0)), MarketPhase.LATE_SCALP, at(dtime(13, 0)))
        if dtime(13, 0) <= t < dtime(14, 50):
            return MarketPhaseState(MarketPhase.LATE_SCALP, "오후_스캘핑", True, "ok", at(dtime(14, 50)), MarketPhase.CLOSE_BET, at(dtime(14, 50)))
        if dtime(14, 50) <= t < dtime(15, 15):
            return MarketPhaseState(MarketPhase.CLOSE_BET, "종가베팅", True, "ok", at(dtime(15, 15)), MarketPhase.AUCTION_LOCKOUT, at(dtime(15, 15)))
        if dtime(15, 15) <= t < dtime(16, 0):
            return MarketPhaseState(MarketPhase.AUCTION_LOCKOUT, "동시호가_잠금", False, "auction_lockout", at(dtime(16, 0)), MarketPhase.CLOSED, at(dtime(16, 0)))
        return MarketPhaseState(MarketPhase.CLOSED, "장종료", False, "market_closed", next_day(dtime(9, 0)), MarketPhase.PRE_OPEN, next_day(dtime(9, 0)))
