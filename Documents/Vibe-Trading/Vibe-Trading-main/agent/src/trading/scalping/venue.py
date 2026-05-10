"""Execution venue models for KRX/NXT-aware trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ListingMarket(str, Enum):
    KOSPI = "kospi"
    KOSDAQ = "kosdaq"
    UNKNOWN = "unknown"


class ExecutionVenue(str, Enum):
    KRX = "krx"
    NXT = "nxt"
    SOR = "sor"
    UNKNOWN = "unknown"


class MarketSession(str, Enum):
    NXT_PRE = "nxt_pre"
    KRX_OPEN_AUCTION = "krx_open_auction"
    KRX_REGULAR = "krx_regular"
    NXT_MAIN = "nxt_main"
    KRX_CLOSE_AUCTION = "krx_close_auction"
    NXT_AFTER = "nxt_after"
    KRX_AFTER_SINGLE = "krx_after_single"
    CLOSED = "closed"


class VenuePolicy(str, Enum):
    KRX_ONLY = "krx_only"
    NXT_ONLY = "nxt_only"
    SOR_BEST_EXECUTION = "sor_best_execution"
    FALLBACK_KRX = "fallback_krx"


class VenueSignal(str, Enum):
    SUPPORTIVE = "supportive"
    RISK = "risk"
    INCONCLUSIVE = "inconclusive"
    MISSING = "missing"


def listing_market_from_legacy(value: str | None) -> ListingMarket:
    text = (value or "").strip().lower()
    if text == "kospi":
        return ListingMarket.KOSPI
    if text == "kosdaq":
        return ListingMarket.KOSDAQ
    return ListingMarket.UNKNOWN


def enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


@dataclass(frozen=True)
class VenueCapability:
    nxt_quote: bool = False
    nxt_realtime_trade: bool = False
    nxt_orderbook: bool = False
    nxt_order: bool = False
    sor_order: bool = False
    nxt_fill_query: bool = False
    nxt_balance: bool = False
    vts_nxt_supported: bool = False

    @property
    def nxt_data_available(self) -> bool:
        return self.nxt_quote or self.nxt_orderbook or self.nxt_realtime_trade


@dataclass
class NxtMarketContext:
    symbol: str
    session: MarketSession
    nxt_price: float = 0.0
    nxt_volume: float = 0.0
    nxt_turnover: float = 0.0
    nxt_vwap: float = 0.0
    nxt_spread: float = 0.0
    nxt_bid_ask_imbalance: float = 0.0
    nxt_trade_count: int = 0
    krx_reference_price: float = 0.0
    krx_turnover: float = 0.0
    krx_spread: float = 0.0
    data_quality: str = "missing"
    ts: datetime | None = None
    turnover_slope: float = 0.0
    trade_count_slope: float = 0.0
    price_momentum_10m: float = 0.0
    bid_wall_fill_ratio: float = 0.0
    displayed_bid_size: float = 0.0
    actual_executed_buy_volume: float = 0.0
    bid_cancel_rate: float = 0.0
    quote_lifetime_ms: float = 0.0
    bid_refresh_quality: float = 0.0
    time_above_krx_close_ratio: float = 0.0
    sell_shock_recovery_pct: float = 0.0
    spread_stability: float = 0.0
    bid_absorption_strength: float = 0.0
    executed_buy_ratio: float = 0.0
    price_hold_under_thin_liquidity: float = 0.0
    opening_auction_imbalance: float = 0.0
    opening_sell_delta: float = 0.0
    first_1m_return: float = 0.0
    first_3m_vwap_gap: float = 0.0
    first_red_low_break: bool = False
    intraday_vwap_gap: float = 0.0
    five_min_high_breakout: bool = False
    cumulative_bid_delta: float = 0.0
    volume_continuity: float = 0.0

    @property
    def venue_price_gap(self) -> float:
        if self.krx_reference_price <= 0 or self.nxt_price <= 0:
            return 0.0
        return (self.nxt_price - self.krx_reference_price) / self.krx_reference_price

    @property
    def venue_liquidity_ratio(self) -> float:
        if self.krx_turnover <= 0:
            return 0.0
        return self.nxt_turnover / self.krx_turnover

    @property
    def venue_spread_gap(self) -> float:
        return self.nxt_spread - self.krx_spread


@dataclass(frozen=True)
class VenueGapDecision:
    signal: VenueSignal
    reason: str
    price_gap: float
    liquidity_ratio: float
    spread_gap: float


def evaluate_venue_gap(
    ctx: NxtMarketContext,
    *,
    min_liquidity_ratio: float = 0.02,
    risk_discount_pct: float = -0.01,
    max_abs_gap_pct: float = 0.02,
) -> VenueGapDecision:
    price_gap = ctx.venue_price_gap
    liq = ctx.venue_liquidity_ratio
    spread_gap = ctx.venue_spread_gap

    if ctx.data_quality != "ok" or ctx.nxt_price <= 0:
        return VenueGapDecision(VenueSignal.MISSING, "nxt_data_missing", price_gap, liq, spread_gap)
    if abs(price_gap) > max_abs_gap_pct and liq >= min_liquidity_ratio:
        return VenueGapDecision(VenueSignal.RISK, "venue_gap_extreme_liquid", price_gap, liq, spread_gap)
    if price_gap <= risk_discount_pct and liq >= min_liquidity_ratio:
        return VenueGapDecision(VenueSignal.RISK, "nxt_discount_liquid", price_gap, liq, spread_gap)
    if price_gap >= 0 and liq >= min_liquidity_ratio:
        return VenueGapDecision(VenueSignal.SUPPORTIVE, "nxt_premium_liquid", price_gap, liq, spread_gap)
    if price_gap >= 0 and liq < min_liquidity_ratio:
        return VenueGapDecision(VenueSignal.INCONCLUSIVE, "nxt_premium_illiquid", price_gap, liq, spread_gap)
    return VenueGapDecision(VenueSignal.INCONCLUSIVE, "nxt_discount_illiquid", price_gap, liq, spread_gap)
