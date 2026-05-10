"""Overnight risk and NXT microstructure decisions for CLOSE_BET positions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .venue import NxtMarketContext, VenueSignal, evaluate_venue_gap


class OvernightAction(str, Enum):
    BLOCK_ENTRY = "block_entry"
    ENTER_REDUCED = "enter_reduced"
    ENTER_NORMAL = "enter_normal"
    PREOPEN_EXIT = "preopen_exit"
    EXIT_AT_OPEN = "exit_at_open"
    PARTIAL_EXIT_THEN_WATCH = "partial_exit_then_watch"
    HOLD_EXTENSION = "hold_extension"


class CloseBetGrade(str, Enum):
    A = "a_hold_candidate"
    B = "b_keep_candidate"
    C = "c_exit_priority"
    D = "d_block_or_reduce"


@dataclass(frozen=True)
class MacroOvernightContext:
    nasdaq_futures_pct: float = 0.0
    sox_pct: float = 0.0
    nvidia_pct: float = 0.0
    adr_pct: float = 0.0
    usdkrw_pct: float = 0.0
    night_future_pct: float = 0.0
    vix_pct: float = 0.0
    global_risk_on_score: float = 50.0


@dataclass(frozen=True)
class OvernightDecision:
    action: OvernightAction
    score: float
    reason: str
    components: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NXTResilienceMetrics:
    time_above_krx_close_ratio: float
    sell_shock_recovery_pct: float
    spread_stability: float
    bid_absorption_strength: float
    executed_buy_ratio: float
    price_hold_under_thin_liquidity: float
    observation_quality: str


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _pos(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return _clamp(value / scale * 100.0)


class FakeLiquidityDetector:
    def score(self, ctx: NxtMarketContext) -> OvernightDecision:
        if ctx.data_quality != "ok":
            return OvernightDecision(
                OvernightAction.EXIT_AT_OPEN,
                45.0,
                "nxt_liquidity_data_missing",
                {"liquidity_trust": 45.0, "fake_bid_ratio": 0.0},
            )
        displayed_bid = ctx.displayed_bid_size
        executed_buy = ctx.actual_executed_buy_volume
        fake_bid_ratio = displayed_bid / max(executed_buy, 1.0) if displayed_bid > 0 else 0.0
        lifetime_score = _clamp(ctx.quote_lifetime_ms / 3000.0 * 100.0)
        fill_score = _clamp(ctx.bid_wall_fill_ratio * 100.0)
        refresh_score = _clamp(ctx.bid_refresh_quality * 100.0)
        cancel_penalty = _clamp(ctx.bid_cancel_rate * 100.0)
        if (
            ctx.bid_wall_fill_ratio == 0
            and ctx.bid_cancel_rate == 0
            and ctx.quote_lifetime_ms == 0
            and ctx.bid_refresh_quality == 0
        ):
            trust = 45.0
            reason = "nxt_liquidity_unobserved_conservative"
        else:
            trust = _clamp(
                0.35 * fill_score
                + 0.25 * lifetime_score
                + 0.20 * refresh_score
                - 0.20 * cancel_penalty
            )
            reason = "nxt_liquidity_trusted" if trust >= 50 else "fake_liquidity_risk"
        if fake_bid_ratio > 10 and trust > 45:
            trust = 45.0
            reason = "fake_bid_wall_detected"
        return OvernightDecision(
            OvernightAction.ENTER_NORMAL if trust >= 50 else OvernightAction.EXIT_AT_OPEN,
            trust,
            reason,
            {
                "liquidity_trust": trust,
                "fill_score": fill_score,
                "quote_lifetime_score": lifetime_score,
                "refresh_score": refresh_score,
                "cancel_penalty": cancel_penalty,
                "fake_bid_ratio": fake_bid_ratio,
            },
        )


class NXTResilienceAnalyzer:
    def metrics(self, ctx: NxtMarketContext) -> NXTResilienceMetrics:
        if ctx.data_quality != "ok":
            return NXTResilienceMetrics(0, 0, 0, 0, 0, 0, "missing")
        thin = ctx.venue_liquidity_ratio < 0.02
        return NXTResilienceMetrics(
            time_above_krx_close_ratio=_clamp(ctx.time_above_krx_close_ratio * 100.0),
            sell_shock_recovery_pct=_clamp(ctx.sell_shock_recovery_pct * 100.0),
            spread_stability=_clamp(ctx.spread_stability * 100.0),
            bid_absorption_strength=_clamp(ctx.bid_absorption_strength * 100.0),
            executed_buy_ratio=_clamp(ctx.executed_buy_ratio * 100.0),
            price_hold_under_thin_liquidity=_clamp(ctx.price_hold_under_thin_liquidity * 100.0),
            observation_quality="thin" if thin else "ok",
        )

    def score(self, ctx: NxtMarketContext) -> OvernightDecision:
        m = self.metrics(ctx)
        if m.observation_quality == "missing":
            return OvernightDecision(
                OvernightAction.EXIT_AT_OPEN,
                45.0,
                "nxt_resilience_missing",
                {"nxt_resilience_score": 45.0, "nxt_observation_quality": 0.0},
                {"observation_quality": "missing"},
            )
        score = _clamp(
            0.30 * m.time_above_krx_close_ratio
            + 0.25 * m.sell_shock_recovery_pct
            + 0.20 * m.spread_stability
            + 0.15 * m.bid_absorption_strength
            + 0.10 * m.price_hold_under_thin_liquidity
        )
        reason = "nxt_resilience_strong" if score >= 70 else "nxt_resilience_neutral" if score >= 50 else "nxt_resilience_weak"
        return OvernightDecision(
            OvernightAction.ENTER_NORMAL if score >= 50 else OvernightAction.EXIT_AT_OPEN,
            score,
            reason,
            {
                "nxt_resilience_score": score,
                "time_above_krx_close": m.time_above_krx_close_ratio,
                "sell_shock_recovery": m.sell_shock_recovery_pct,
                "spread_stability": m.spread_stability,
                "bid_absorption_strength": m.bid_absorption_strength,
                "executed_buy_ratio": m.executed_buy_ratio,
                "price_hold_under_thin_liquidity": m.price_hold_under_thin_liquidity,
                "nxt_observation_quality": 1.0 if m.observation_quality == "ok" else 0.5,
            },
            {"observation_quality": m.observation_quality},
        )


class ExhaustionTrapDetector:
    def score(self, ctx: NxtMarketContext) -> OvernightDecision:
        gap = ctx.venue_price_gap
        volume_decay = 100.0 if ctx.turnover_slope < 0 else 0.0
        trade_decay = 100.0 if ctx.trade_count_slope < 0 else 0.0
        spread_risk = _pos(ctx.nxt_spread, 0.01)
        price_gap_risk = _pos(gap - 0.015, 0.02)
        thin_late_print = 100.0 if ctx.price_momentum_10m > 0 and ctx.turnover_slope < 0 else 0.0
        score = _clamp(
            0.30 * price_gap_risk
            + 0.25 * volume_decay
            + 0.15 * trade_decay
            + 0.20 * spread_risk
            + 0.10 * thin_late_print
        )
        if score >= 70:
            action = OvernightAction.PREOPEN_EXIT
            reason = "nxt_exhaustion_trap_high"
        elif score >= 50:
            action = OvernightAction.EXIT_AT_OPEN
            reason = "nxt_exhaustion_trap_medium"
        else:
            action = OvernightAction.ENTER_NORMAL
            reason = "nxt_exhaustion_trap_low"
        return OvernightDecision(
            action,
            score,
            reason,
            {
                "exhaustion_score": score,
                "price_gap_risk": price_gap_risk,
                "volume_decay": volume_decay,
                "trade_decay": trade_decay,
                "spread_risk": spread_risk,
                "thin_late_print": thin_late_print,
            },
        )


class GapRiskModel:
    def score(self, macro: MacroOvernightContext | None = None) -> OvernightDecision:
        macro = macro or MacroOvernightContext()
        us_index_risk = _clamp((-macro.nasdaq_futures_pct) / 0.02 * 100.0)
        sector_risk = _clamp((-(macro.sox_pct + macro.nvidia_pct) / 2.0) / 0.02 * 100.0)
        fx_risk = _clamp(macro.usdkrw_pct / 0.01 * 100.0)
        adr_gap_risk = _clamp((-macro.adr_pct) / 0.02 * 100.0)
        vol_risk = _clamp(macro.vix_pct / 0.10 * 100.0)
        local_risk = _clamp((-macro.night_future_pct) / 0.02 * 100.0)
        risk_off = _clamp(100.0 - macro.global_risk_on_score)
        score = _clamp(
            0.20 * us_index_risk
            + 0.20 * sector_risk
            + 0.15 * fx_risk
            + 0.15 * adr_gap_risk
            + 0.10 * vol_risk
            + 0.10 * local_risk
            + 0.10 * risk_off
        )
        if score >= 70:
            action = OvernightAction.BLOCK_ENTRY
            reason = "overnight_macro_risk_high"
        elif score >= 50:
            action = OvernightAction.ENTER_REDUCED
            reason = "overnight_macro_risk_medium"
        else:
            action = OvernightAction.ENTER_NORMAL
            reason = "overnight_macro_risk_low"
        return OvernightDecision(
            action,
            score,
            reason,
            {
                "overnight_risk": score,
                "us_index_risk": us_index_risk,
                "sector_risk": sector_risk,
                "fx_risk": fx_risk,
                "adr_gap_risk": adr_gap_risk,
                "volatility_risk": vol_risk,
                "local_theme_risk": local_risk,
                "risk_off": risk_off,
            },
        )


class NXTOrderFlowAnalyzer:
    def score(self, ctx: NxtMarketContext) -> OvernightDecision:
        gap = evaluate_venue_gap(ctx)
        liquidity_score = _clamp(ctx.venue_liquidity_ratio / 0.05 * 100.0)
        imbalance_score = _clamp((ctx.nxt_bid_ask_imbalance - 1.0) / 0.5 * 100.0)
        spread_score = _clamp(100.0 - _pos(ctx.nxt_spread, 0.01))
        score = _clamp(0.35 * liquidity_score + 0.35 * imbalance_score + 0.30 * spread_score)
        if gap.signal == VenueSignal.RISK:
            score = min(score, 35.0)
        reason = gap.reason if gap.signal != VenueSignal.MISSING else "nxt_orderflow_missing"
        return OvernightDecision(
            OvernightAction.ENTER_NORMAL if score >= 55 else OvernightAction.EXIT_AT_OPEN,
            score,
            reason,
            {
                "nxt_orderflow_score": score,
                "venue_price_gap": gap.price_gap,
                "venue_liquidity_ratio": gap.liquidity_ratio,
                "venue_spread_gap": gap.spread_gap,
            },
        )


class NXTConfidenceAdjuster:
    def evaluate(
        self,
        ctx: NxtMarketContext,
        *,
        fake: OvernightDecision,
        resilience: OvernightDecision,
        exhaustion: OvernightDecision,
        orderflow: OvernightDecision,
    ) -> OvernightDecision:
        gap = evaluate_venue_gap(ctx)
        adjustment = 0.0
        morning_exit_priority = 40.0
        position_size_multiplier = 1.0
        hold_extension_allowed = False

        if gap.signal == VenueSignal.SUPPORTIVE:
            adjustment += 10.0
        elif gap.signal == VenueSignal.RISK:
            adjustment -= 10.0
            morning_exit_priority += 15.0
        elif gap.signal == VenueSignal.MISSING:
            adjustment -= 5.0
            morning_exit_priority += 10.0

        if resilience.score >= 70:
            adjustment += 12.0
            hold_extension_allowed = True
        elif resilience.score >= 50:
            adjustment += 4.0
        else:
            adjustment -= 8.0
            morning_exit_priority += 10.0

        if fake.score < 35:
            adjustment -= 8.0
            morning_exit_priority += 15.0
            hold_extension_allowed = False
        if exhaustion.score >= 70:
            adjustment -= 15.0
            morning_exit_priority += 25.0
            position_size_multiplier = min(position_size_multiplier, 0.5)
            hold_extension_allowed = False
        elif exhaustion.score >= 50:
            adjustment -= 8.0
            morning_exit_priority += 12.0
            position_size_multiplier = min(position_size_multiplier, 0.7)

        thin_but_resilient = (
            resilience.metadata.get("observation_quality") == "thin"
            and resilience.score >= 60
            and ctx.venue_price_gap >= -0.003
        )
        if thin_but_resilient:
            adjustment += 8.0
            morning_exit_priority = max(35.0, morning_exit_priority - 10.0)

        if resilience.score >= 70 and fake.score >= 45 and gap.signal != VenueSignal.RISK:
            grade = CloseBetGrade.A
            reason = "grade_a_nxt_resilient"
        elif thin_but_resilient or resilience.score >= 50:
            grade = CloseBetGrade.B
            reason = "grade_b_keep_candidate"
        elif gap.signal == VenueSignal.RISK or exhaustion.score >= 50 or fake.score < 35:
            grade = CloseBetGrade.C
            reason = "grade_c_exit_priority"
            position_size_multiplier = min(position_size_multiplier, 0.5)
        else:
            grade = CloseBetGrade.B
            reason = "grade_b_krx_primary_preserved"

        return OvernightDecision(
            OvernightAction.ENTER_NORMAL if grade in {CloseBetGrade.A, CloseBetGrade.B} else OvernightAction.ENTER_REDUCED,
            _clamp(50.0 + adjustment),
            reason,
            {
                "nxt_confidence_adjustment": adjustment,
                "morning_exit_priority": _clamp(morning_exit_priority),
                "position_size_multiplier": position_size_multiplier,
                "hold_extension_allowed": 1.0 if hold_extension_allowed else 0.0,
            },
            {
                "close_bet_grade": grade.value,
                "thin_but_resilient": thin_but_resilient,
            },
        )


class MorningExitEngine:
    def decide(self, ctx: NxtMarketContext, macro: MacroOvernightContext | None = None) -> OvernightDecision:
        fake = FakeLiquidityDetector().score(ctx)
        exhaust = ExhaustionTrapDetector().score(ctx)
        gap_risk = GapRiskModel().score(macro)
        nxt_pre_discount = _pos(-ctx.venue_price_gap, 0.02)
        opening_sell = _clamp(-ctx.opening_sell_delta / 100000.0 * 100.0)
        auction_sell = _clamp((1.0 - ctx.opening_auction_imbalance) / 0.5 * 100.0)
        first_bar_fail = 100.0 if ctx.first_1m_return < -0.005 or ctx.first_red_low_break else 0.0
        vwap_fail = 100.0 if ctx.first_3m_vwap_gap < -0.002 or ctx.intraday_vwap_gap < -0.002 else 0.0
        score = _clamp(
            0.20 * exhaust.score
            + 0.20 * gap_risk.score
            + 0.20 * nxt_pre_discount
            + 0.15 * (100.0 - fake.score)
            + 0.10 * opening_sell
            + 0.05 * auction_sell
            + 0.05 * first_bar_fail
            + 0.05 * vwap_fail
        )
        if score >= 70 or (nxt_pre_discount >= 75 and (opening_sell >= 75 or first_bar_fail >= 100)):
            action = OvernightAction.PREOPEN_EXIT
            reason = "morning_exit_preopen_risk"
            score = max(score, 70.0)
        elif score >= 50:
            action = OvernightAction.EXIT_AT_OPEN
            reason = "morning_exit_open_risk"
        else:
            action = OvernightAction.PARTIAL_EXIT_THEN_WATCH
            reason = "morning_exit_watch_allowed"
        components = {
            **fake.components,
            **exhaust.components,
            **gap_risk.components,
            "preopen_exit_score": score,
            "nxt_pre_discount": nxt_pre_discount,
            "opening_sell": opening_sell,
            "auction_sell": auction_sell,
            "first_bar_fail": first_bar_fail,
            "vwap_fail": vwap_fail,
        }
        return OvernightDecision(action, score, reason, components)


class HoldExtensionEngine:
    def decide(self, ctx: NxtMarketContext) -> OvernightDecision:
        opening_strength = _clamp(ctx.first_1m_return / 0.01 * 100.0)
        vwap_hold = 100.0 if ctx.intraday_vwap_gap > 0 or ctx.first_3m_vwap_gap > 0 else 0.0
        bid_delta = _clamp(ctx.cumulative_bid_delta / 100000.0 * 100.0)
        volume = _clamp(ctx.volume_continuity * 100.0)
        venue_quality = NXTOrderFlowAnalyzer().score(ctx).score
        breakout = 100.0 if ctx.five_min_high_breakout else 0.0
        score = _clamp(
            0.20 * opening_strength
            + 0.20 * vwap_hold
            + 0.20 * bid_delta
            + 0.15 * volume
            + 0.15 * venue_quality
            + 0.10 * breakout
        )
        if score >= 75:
            action = OvernightAction.HOLD_EXTENSION
            reason = "hold_extension_strong"
        elif score >= 60:
            action = OvernightAction.PARTIAL_EXIT_THEN_WATCH
            reason = "hold_extension_partial"
        else:
            action = OvernightAction.EXIT_AT_OPEN
            reason = "hold_extension_rejected"
        return OvernightDecision(
            action,
            score,
            reason,
            {
                "hold_extension_score": score,
                "opening_strength": opening_strength,
                "vwap_hold": vwap_hold,
                "bid_delta": bid_delta,
                "volume_continuity": volume,
                "venue_quality": venue_quality,
                "five_min_breakout": breakout,
            },
        )


class OvernightEngine:
    def __init__(self, macro_context: MacroOvernightContext | None = None) -> None:
        self._macro_context = macro_context or MacroOvernightContext()
        self.fake_liquidity = FakeLiquidityDetector()
        self.exhaustion = ExhaustionTrapDetector()
        self.gap_risk = GapRiskModel()
        self.orderflow = NXTOrderFlowAnalyzer()
        self.resilience = NXTResilienceAnalyzer()
        self.confidence = NXTConfidenceAdjuster()
        self.morning_exit = MorningExitEngine()
        self.hold_extension = HoldExtensionEngine()

    def evaluate_entry(self, ctx: NxtMarketContext) -> OvernightDecision:
        fake = self.fake_liquidity.score(ctx)
        exhaust = self.exhaustion.score(ctx)
        gap_risk = self.gap_risk.score(self._macro_context)
        orderflow = self.orderflow.score(ctx)
        resilience = self.resilience.score(ctx)
        confidence = self.confidence.evaluate(
            ctx,
            fake=fake,
            resilience=resilience,
            exhaustion=exhaust,
            orderflow=orderflow,
        )
        risk_score = _clamp(
            0.25 * exhaust.score
            + 0.25 * gap_risk.score
            + 0.15 * (100.0 - fake.score)
            + 0.10 * (100.0 - orderflow.score)
            + 0.15 * (100.0 - resilience.score)
            + 0.10 * _pos(abs(ctx.venue_price_gap) - 0.02, 0.02)
        )
        if gap_risk.action == OvernightAction.BLOCK_ENTRY:
            action = OvernightAction.BLOCK_ENTRY
            reason = "overnight_macro_hard_block"
        elif risk_score >= 65 or confidence.metadata.get("close_bet_grade") == CloseBetGrade.C.value:
            action = OvernightAction.ENTER_REDUCED
            reason = "overnight_entry_reduced"
        else:
            action = OvernightAction.ENTER_NORMAL
            reason = "overnight_entry_allowed"
        components = {
            **fake.components,
            **exhaust.components,
            **gap_risk.components,
            **orderflow.components,
            **resilience.components,
            **confidence.components,
            "overnight_entry_risk": risk_score,
        }
        return OvernightDecision(action, risk_score, reason, components, confidence.metadata)

    def decide_morning(self, ctx: NxtMarketContext) -> OvernightDecision:
        exit_decision = self.morning_exit.decide(ctx, self._macro_context)
        hold_decision = self.hold_extension.decide(ctx)
        if exit_decision.score >= 50:
            return exit_decision
        if hold_decision.action == OvernightAction.HOLD_EXTENSION:
            return OvernightDecision(
                OvernightAction.HOLD_EXTENSION,
                hold_decision.score,
                hold_decision.reason,
                {**exit_decision.components, **hold_decision.components},
            )
        return OvernightDecision(
            OvernightAction.EXIT_AT_OPEN,
            max(exit_decision.score, 100.0 - hold_decision.score),
            "default_open_exit",
            {**exit_decision.components, **hold_decision.components},
        )
