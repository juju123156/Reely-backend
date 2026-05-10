"""Morning CLOSE_BET position decision engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MorningAction(str, Enum):
    PREOPEN_EXIT = "preopen_exit"
    OPEN_EXIT = "open_exit"
    HOLD_TO_0910 = "hold_to_0910"
    HOLD_EXTENSION = "hold_extension"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class MorningDecisionInput:
    symbol: str
    pnl_pct: float
    close_bet_grade: str = "b_keep_candidate"
    nxt_discount_pct: float = 0.0
    macro_risk_score: float = 0.0
    fake_bid_risk: float | None = None
    first_1m_low_break: bool | None = None
    first_3m_high_break: bool | None = None
    vwap_hold: bool | None = None
    cumulative_bid_delta: float | None = None
    opening_sell_pressure: float | None = None
    trading_value_drop_3m: bool | None = None
    data_quality: str = "missing"  # full | partial | missing
    current_time: datetime | None = None


@dataclass(frozen=True)
class MorningDecision:
    action: MorningAction
    confidence: float
    exit_qty_ratio: float
    reason_codes: list[str] = field(default_factory=list)
    data_quality: str = "missing"
    score_breakdown: dict[str, float] = field(default_factory=dict)

    def to_log_dict(self, *, position_type: str = "close_bet", strategy_id: str = "") -> dict:
        return {
            "event": "MORNING_POSITION_DECISION",
            "position_type": position_type,
            "strategy_id": strategy_id,
            "action": self.action.value,
            "exit_qty_ratio": self.exit_qty_ratio,
            "confidence": round(self.confidence, 2),
            "data_quality": self.data_quality,
            "reason_codes": self.reason_codes,
            "score_breakdown": {k: round(v, 4) for k, v in self.score_breakdown.items()},
        }

    def to_json(self, *, position_type: str = "close_bet", strategy_id: str = "") -> str:
        return json.dumps(self.to_log_dict(position_type=position_type, strategy_id=strategy_id), ensure_ascii=False)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class MorningPositionDecisionEngine:
    def decide(self, inp: MorningDecisionInput) -> MorningDecision:
        if inp.data_quality == "missing":
            if inp.pnl_pct > 0:
                return MorningDecision(
                    MorningAction.OPEN_EXIT,
                    65.0,
                    1.0,
                    ["data_missing", "pnl_positive_defensive_exit"],
                    inp.data_quality,
                    {"pnl_pct": inp.pnl_pct},
                )
            return MorningDecision(
                MorningAction.HOLD_TO_0910,
                55.0,
                0.0,
                ["data_missing", "pnl_negative_wait_first_candle"],
                inp.data_quality,
                {"pnl_pct": inp.pnl_pct},
            )

        reason_codes: list[str] = []
        macro = _clamp(inp.macro_risk_score)
        nxt_discount = _clamp(max(0.0, -inp.nxt_discount_pct) / 0.02 * 100.0)
        fake_bid = _clamp(inp.fake_bid_risk or 0.0)
        first_low = 100.0 if inp.first_1m_low_break else 0.0
        opening_sell = _clamp(((inp.opening_sell_pressure or 0.0) - 0.5) / 0.3 * 100.0)
        vwap_lost = 100.0 if inp.vwap_hold is False else 0.0
        bid_delta_neg = _clamp(max(0.0, -(inp.cumulative_bid_delta or 0.0)) / 100000.0 * 100.0)
        value_drop = 100.0 if inp.trading_value_drop_3m else 0.0
        risk = _clamp(
            0.20 * macro
            + 0.20 * nxt_discount
            + 0.15 * fake_bid
            + 0.15 * first_low
            + 0.10 * opening_sell
            + 0.10 * vwap_lost
            + 0.05 * bid_delta_neg
            + 0.05 * value_drop
        )
        if inp.data_quality == "partial":
            risk = _clamp(risk + 8.0)
            reason_codes.append("data_quality_partial")
        if macro >= 70:
            reason_codes.append("macro_risk_high")
        if nxt_discount >= 50:
            reason_codes.append("nxt_discount")
        if fake_bid >= 70:
            reason_codes.append("fake_bid_risk_high")
        if inp.first_1m_low_break:
            reason_codes.append("first_1m_low_break")
        if inp.vwap_hold is False:
            reason_codes.append("vwap_lost")
        if inp.opening_sell_pressure is not None and inp.opening_sell_pressure >= 0.58:
            reason_codes.append("opening_sell_pressure")
        if inp.trading_value_drop_3m:
            reason_codes.append("trading_value_drop_3m")

        hold_score = self._hold_score(inp)
        breakdown = {
            "risk_score": risk,
            "hold_score": hold_score,
            "macro_risk_score": macro,
            "nxt_discount_score": nxt_discount,
            "fake_bid_risk": fake_bid,
            "first_1m_low_break": first_low,
            "opening_sell_pressure": opening_sell,
            "vwap_lost": vwap_lost,
            "bid_delta_negative": bid_delta_neg,
            "trading_value_drop_3m": value_drop,
            "pnl_pct": inp.pnl_pct,
        }
        if inp.first_1m_low_break and (fake_bid >= 70 or inp.vwap_hold is False or opening_sell >= 50):
            return MorningDecision(
                MorningAction.OPEN_EXIT,
                max(65.0, risk),
                1.0,
                reason_codes or ["first_1m_low_break"],
                inp.data_quality,
                breakdown,
            )
        if risk >= 75:
            return MorningDecision(MorningAction.PREOPEN_EXIT, risk, 1.0, reason_codes or ["risk_high"], inp.data_quality, breakdown)
        if risk >= 60:
            return MorningDecision(MorningAction.OPEN_EXIT, risk, 1.0, reason_codes or ["risk_medium_high"], inp.data_quality, breakdown)
        if risk >= 40:
            return MorningDecision(MorningAction.HOLD_TO_0910, 100.0 - risk, 0.5 if inp.pnl_pct > 0 else 0.0, reason_codes or ["watch_to_0910"], inp.data_quality, breakdown)
        if hold_score >= 75:
            return MorningDecision(MorningAction.HOLD_EXTENSION, hold_score, 0.0, ["hold_extension_conditions_met"], inp.data_quality, breakdown)
        return MorningDecision(MorningAction.NO_ACTION, max(50.0, 100.0 - risk), 0.0, reason_codes or ["no_action"], inp.data_quality, breakdown)

    @staticmethod
    def _hold_score(inp: MorningDecisionInput) -> float:
        vwap = 100.0 if inp.vwap_hold else 0.0
        high_break = 100.0 if inp.first_3m_high_break else 0.0
        bid_delta = _clamp((inp.cumulative_bid_delta or 0.0) / 100000.0 * 100.0)
        sell_absorption = _clamp((0.58 - (inp.opening_sell_pressure or 0.5)) / 0.25 * 100.0)
        grade_bonus = 15.0 if inp.close_bet_grade.startswith("a_") else 8.0 if inp.close_bet_grade.startswith("b_") else 0.0
        return _clamp(
            0.30 * vwap
            + 0.25 * high_break
            + 0.25 * bid_delta
            + 0.15 * sell_absorption
            + grade_bonus
        )
