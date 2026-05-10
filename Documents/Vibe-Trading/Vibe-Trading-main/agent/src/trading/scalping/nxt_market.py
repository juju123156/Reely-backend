"""NXT-aware market context, scoring, and fallback policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .venue import (
    ExecutionVenue,
    MarketSession,
    NxtMarketContext,
    VenueCapability,
    VenueGapDecision,
    VenuePolicy,
    VenueSignal,
    evaluate_venue_gap,
)
from .overnight_engine import CloseBetGrade, OvernightAction, OvernightEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NxtSignalDecision:
    signal: VenueSignal
    reason: str
    risk_delta: float = 0.0
    allow_add: bool = False
    raise_exit_priority: bool = False


@dataclass(frozen=True)
class VenueRoutingDecision:
    preferred_venue: ExecutionVenue
    actual_venue: ExecutionVenue
    venue_policy: VenuePolicy
    reason: str


def detect_venue_capability(adapter: Any, *, env: str = "demo") -> VenueCapability:
    """Best-effort capability probe without placing orders."""
    if hasattr(adapter, "venue_capability"):
        try:
            raw = adapter.venue_capability(env_dv=env)
            if isinstance(raw, VenueCapability):
                return raw
            if isinstance(raw, dict):
                return VenueCapability(**{k: bool(v) for k, v in raw.items() if k in VenueCapability.__dataclass_fields__})
        except Exception as exc:
            logger.warning("[NXT_CAPABILITY] probe failed: %s", exc)
    return VenueCapability()


def choose_routing(
    capability: VenueCapability,
    *,
    requested_policy: VenuePolicy,
    env: str = "demo",
    dry_run: bool = True,
) -> VenueRoutingDecision:
    if requested_policy == VenuePolicy.KRX_ONLY:
        return VenueRoutingDecision(ExecutionVenue.KRX, ExecutionVenue.KRX, VenuePolicy.KRX_ONLY, "krx_only")
    if requested_policy == VenuePolicy.SOR_BEST_EXECUTION and capability.sor_order:
        return VenueRoutingDecision(ExecutionVenue.SOR, ExecutionVenue.UNKNOWN, VenuePolicy.SOR_BEST_EXECUTION, "sor_supported")
    if (
        requested_policy == VenuePolicy.NXT_ONLY
        and capability.nxt_order
        and (env != "demo" or dry_run or capability.vts_nxt_supported)
    ):
        return VenueRoutingDecision(ExecutionVenue.NXT, ExecutionVenue.NXT, VenuePolicy.NXT_ONLY, "nxt_order_supported")
    if requested_policy == VenuePolicy.NXT_ONLY and env == "demo" and not capability.vts_nxt_supported:
        return VenueRoutingDecision(ExecutionVenue.KRX, ExecutionVenue.KRX, VenuePolicy.FALLBACK_KRX, "vts_nxt_direct_order_unsupported")
    return VenueRoutingDecision(ExecutionVenue.KRX, ExecutionVenue.KRX, VenuePolicy.FALLBACK_KRX, "venue_order_unsupported")


def build_nxt_context(
    adapter: Any,
    symbol: str,
    *,
    session: MarketSession,
    env: str = "demo",
    krx_reference_price: float = 0.0,
    krx_turnover: float = 0.0,
    krx_spread: float = 0.0,
) -> NxtMarketContext:
    """Read NXT context when adapter supports it; otherwise return missing context."""
    getter = getattr(adapter, "get_nxt_market_context", None)
    if getter:
        try:
            raw = getter(symbol, session=session.value, env_dv=env)
            if raw and raw.get("status", "ok") == "ok":
                return NxtMarketContext(
                    symbol=symbol,
                    session=session,
                    nxt_price=float(raw.get("nxt_price") or raw.get("price") or 0),
                    nxt_volume=float(raw.get("nxt_volume") or raw.get("volume") or 0),
                    nxt_turnover=float(raw.get("nxt_turnover") or raw.get("turnover") or 0),
                    nxt_vwap=float(raw.get("nxt_vwap") or raw.get("vwap") or 0),
                    nxt_spread=float(raw.get("nxt_spread") or raw.get("spread") or 0),
                    nxt_bid_ask_imbalance=float(raw.get("nxt_bid_ask_imbalance") or raw.get("bid_ask_imbalance") or 0),
                    nxt_trade_count=int(raw.get("nxt_trade_count") or raw.get("trade_count") or 0),
                    krx_reference_price=krx_reference_price,
                    krx_turnover=krx_turnover,
                    krx_spread=krx_spread,
                    data_quality="ok",
                    ts=datetime.now(),
                    turnover_slope=float(raw.get("turnover_slope") or 0),
                    trade_count_slope=float(raw.get("trade_count_slope") or 0),
                    price_momentum_10m=float(raw.get("price_momentum_10m") or 0),
                    bid_wall_fill_ratio=float(raw.get("bid_wall_fill_ratio") or 0),
                    displayed_bid_size=float(raw.get("displayed_bid_size") or 0),
                    actual_executed_buy_volume=float(raw.get("actual_executed_buy_volume") or 0),
                    bid_cancel_rate=float(raw.get("bid_cancel_rate") or 0),
                    quote_lifetime_ms=float(raw.get("quote_lifetime_ms") or 0),
                    bid_refresh_quality=float(raw.get("bid_refresh_quality") or 0),
                    time_above_krx_close_ratio=float(raw.get("time_above_krx_close_ratio") or 0),
                    sell_shock_recovery_pct=float(raw.get("sell_shock_recovery_pct") or 0),
                    spread_stability=float(raw.get("spread_stability") or 0),
                    bid_absorption_strength=float(raw.get("bid_absorption_strength") or 0),
                    executed_buy_ratio=float(raw.get("executed_buy_ratio") or 0),
                    price_hold_under_thin_liquidity=float(raw.get("price_hold_under_thin_liquidity") or 0),
                    opening_auction_imbalance=float(raw.get("opening_auction_imbalance") or 0),
                    opening_sell_delta=float(raw.get("opening_sell_delta") or 0),
                    first_1m_return=float(raw.get("first_1m_return") or 0),
                    first_3m_vwap_gap=float(raw.get("first_3m_vwap_gap") or 0),
                    first_red_low_break=bool(raw.get("first_red_low_break") or False),
                    intraday_vwap_gap=float(raw.get("intraday_vwap_gap") or 0),
                    five_min_high_breakout=bool(raw.get("five_min_high_breakout") or False),
                    cumulative_bid_delta=float(raw.get("cumulative_bid_delta") or 0),
                    volume_continuity=float(raw.get("volume_continuity") or 0),
                )
        except Exception as exc:
            logger.warning("[NXT_CONTEXT] failed symbol=%s session=%s error=%s", symbol, session.value, exc)
    return NxtMarketContext(
        symbol=symbol,
        session=session,
        krx_reference_price=krx_reference_price,
        krx_turnover=krx_turnover,
        krx_spread=krx_spread,
        data_quality="missing",
        ts=datetime.now(),
    )


def evaluate_nxt_after(ctx: NxtMarketContext) -> NxtSignalDecision:
    gap = evaluate_venue_gap(ctx)
    if gap.signal == VenueSignal.MISSING:
        return NxtSignalDecision(VenueSignal.MISSING, "nxt_after_data_missing", risk_delta=0.1)
    if gap.signal == VenueSignal.RISK:
        return NxtSignalDecision(VenueSignal.RISK, gap.reason, risk_delta=0.3, raise_exit_priority=True)
    if gap.signal == VenueSignal.SUPPORTIVE and ctx.nxt_bid_ask_imbalance >= 1.0:
        return NxtSignalDecision(VenueSignal.SUPPORTIVE, gap.reason, risk_delta=-0.1, allow_add=True)
    return NxtSignalDecision(VenueSignal.INCONCLUSIVE, gap.reason, risk_delta=0.05)


def evaluate_nxt_pre(ctx: NxtMarketContext) -> NxtSignalDecision:
    gap = evaluate_venue_gap(ctx, min_liquidity_ratio=0.01, risk_discount_pct=-0.01)
    if gap.signal == VenueSignal.MISSING:
        return NxtSignalDecision(VenueSignal.MISSING, "nxt_pre_data_missing", raise_exit_priority=False)
    if gap.signal == VenueSignal.RISK:
        return NxtSignalDecision(VenueSignal.RISK, gap.reason, risk_delta=0.5, raise_exit_priority=True)
    if gap.signal == VenueSignal.SUPPORTIVE:
        return NxtSignalDecision(VenueSignal.SUPPORTIVE, gap.reason, risk_delta=-0.1)
    return NxtSignalDecision(VenueSignal.INCONCLUSIVE, gap.reason, risk_delta=0.1)


def close_bet_nxt_score_adjustment(ctx: NxtMarketContext) -> tuple[float, dict]:
    gap: VenueGapDecision = evaluate_venue_gap(ctx)
    if gap.signal == VenueSignal.MISSING:
        return -10.0, {
            "nxt_data_missing": True,
            "venue_price_gap": gap.price_gap,
            "venue_liquidity_ratio": gap.liquidity_ratio,
            "venue_gap_reason": gap.reason,
        }
    overnight = OvernightEngine().evaluate_entry(ctx)
    score = 0.0
    if gap.signal == VenueSignal.SUPPORTIVE:
        score += 15.0
    elif gap.signal == VenueSignal.RISK:
        score -= 25.0
    else:
        score -= 5.0
    grade = str(overnight.metadata.get("close_bet_grade") or "")
    if overnight.action == OvernightAction.BLOCK_ENTRY:
        score -= 100.0
    elif overnight.action == OvernightAction.ENTER_REDUCED:
        score -= 8.0
    score += float(overnight.components.get("nxt_confidence_adjustment") or 0.0)
    if grade == CloseBetGrade.A.value:
        score += 8.0
    elif grade == CloseBetGrade.B.value:
        score += 3.0
    elif grade == CloseBetGrade.C.value:
        score -= 8.0
    if ctx.nxt_bid_ask_imbalance >= 1.2:
        score += 5.0
    if ctx.nxt_spread > 0.005:
        score -= 5.0
    return score, {
        "nxt_data_missing": False,
        "venue_price_gap": gap.price_gap,
        "venue_liquidity_ratio": gap.liquidity_ratio,
        "venue_spread": ctx.nxt_spread,
        "venue_gap_reason": gap.reason,
        "nxt_after_price": ctx.nxt_price if ctx.session == MarketSession.NXT_AFTER else 0,
        "nxt_pre_price": ctx.nxt_price if ctx.session == MarketSession.NXT_PRE else 0,
        "nxt_after_volume": ctx.nxt_volume if ctx.session == MarketSession.NXT_AFTER else 0,
        "nxt_pre_volume": ctx.nxt_volume if ctx.session == MarketSession.NXT_PRE else 0,
        "overnight_action": overnight.action.value,
        "overnight_entry_risk": overnight.score,
        "overnight_reason": overnight.reason,
        "close_bet_grade": grade,
        **overnight.components,
        **overnight.metadata,
    }
