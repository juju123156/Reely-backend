"""KRX 시장 규정 유틸리티 — 호가단위(tick size) 보정."""

from __future__ import annotations

import math

# ─── KOSPI 호가단위 (가격 < threshold → tick) ─────────────────────────────────
_KOSPI_TICK_TABLE: list[tuple[float, int]] = [
    (2_000,        1),
    (5_000,        5),
    (20_000,      10),
    (50_000,      50),
    (200_000,    100),
    (500_000,    500),
    (math.inf, 1_000),
]

# ─── KOSDAQ 호가단위 ──────────────────────────────────────────────────────────
_KOSDAQ_TICK_TABLE: list[tuple[float, int]] = [
    (1_000,        1),
    (5_000,        5),
    (10_000,      10),
    (50_000,      50),
    (100_000,    100),
    (500_000,    500),
    (math.inf, 1_000),
]


def get_tick_size(price: float, market: str = "KOSDAQ") -> int:
    """주어진 가격의 호가단위(원) 반환."""
    table = _KOSPI_TICK_TABLE if market.upper() == "KOSPI" else _KOSDAQ_TICK_TABLE
    for threshold, tick in table:
        if price < threshold:
            return tick
    return 1_000


def round_to_tick(price: float, market: str = "KOSDAQ", mode: str = "down") -> int:
    """
    가격을 호가단위에 맞게 보정.

    mode="down" — 매수 지정가: 내림 (호가 이탈 방지)
    mode="up"   — 매도 지정가: 올림 (호가 이탈 방지)
    """
    if price <= 0:
        return 0
    tick = get_tick_size(price, market)
    if mode == "up":
        return int(math.ceil(price / tick) * tick)
    return int(price // tick * tick)


def calc_round_trip_cost(price: float, market: str = "KOSDAQ") -> float:
    """왕복 거래비용 = (수수료 × 2 + 매도세) × price."""
    from .constants import COMMISSION_RATE, TAX_RATE_KOSDAQ, TAX_RATE_KOSPI
    tax = TAX_RATE_KOSPI if market.upper() == "KOSPI" else TAX_RATE_KOSDAQ
    return price * (COMMISSION_RATE * 2 + tax)
