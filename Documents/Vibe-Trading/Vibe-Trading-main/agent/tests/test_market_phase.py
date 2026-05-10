from __future__ import annotations

from datetime import datetime

from src.trading.scalping.market_phase import MarketPhase, MarketPhaseResolver


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 9, hour, minute)


def test_market_phase_resolver_core_windows():
    r = MarketPhaseResolver()

    assert r.resolve(_dt(9, 10)).phase == MarketPhase.OPENING_MOMENTUM
    assert r.resolve(_dt(9, 30)).phase == MarketPhase.MORNING_SCALP
    assert r.resolve(_dt(11, 0)).phase == MarketPhase.MIDDAY_VWAP
    assert r.resolve(_dt(13, 30)).phase == MarketPhase.LATE_SCALP
    assert r.resolve(_dt(14, 55)).phase == MarketPhase.CLOSE_BET
    assert r.resolve(_dt(15, 20)).phase == MarketPhase.AUCTION_LOCKOUT
    assert r.resolve(_dt(16, 1)).phase == MarketPhase.CLOSED
