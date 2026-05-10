"""Operational diagnostics for regime blocks and no-entry visibility."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock

from src.trading.scalping.bot import BotStatus, ScalpingBot
from src.trading.scalping.constants import (
    API_STALL_SEC,
    REGIME_CANDIDATE_TTL_SEC,
    REGIME_CONFIRM_SECS,
    RESTART_REGIME_CONFIRM_SECS,
    STRONG_REGIME_CONFIRM_SECS,
)
from src.trading.scalping.events import TickEvent
from src.trading.scalping.market_regime import (
    MarketRegime,
    MarketRegimeAnalyzer,
    StrategyBlockReason,
)
from src.trading.scalping.signal_engine import SignalEngine
from src.trading.scalping.vwap import Candle


def _candidate(change_pct: float = 0.04, vol_ratio: float = 2.0) -> MagicMock:
    c = MagicMock()
    c.change_pct = change_pct
    c.vol_ratio = vol_ratio
    return c


def _normal_candidates(n: int = 10) -> list[MagicMock]:
    return [_candidate(change_pct=0.05, vol_ratio=2.0) for _ in range(n)]


def _aggressive_candidates(n: int = 10) -> list[MagicMock]:
    return [_candidate(change_pct=0.08, vol_ratio=5.0) for _ in range(n)]


def _tick(symbol: str = "A005930", price: float = 72_000.0) -> TickEvent:
    return TickEvent(
        symbol=symbol,
        price=price,
        buy_vol_total=6_000,
        sell_vol_total=4_000,
        bid_qty=2_000,
        ask_qty=1_000,
        tick_vol=100,
        acml_vol=1_000,
        acml_tr_pbmn=72_000_000,
        time_str="103000",
        bid1_price=71_900,
        ask1_price=72_100,
    )


def test_regime_confirming_not_hard_no_trade():
    analyzer = MarketRegimeAnalyzer()

    regime, _ = analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())
    rd = analyzer.to_dict()

    assert regime == MarketRegime.NO_TRADE
    assert rd["candidate_regime"] == MarketRegime.KOSDAQ_NORMAL.value
    assert rd["hard_no_trade"] is False


def test_restart_confirm_secs_shortened():
    analyzer = MarketRegimeAnalyzer()

    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())

    assert analyzer.to_dict()["confirm_required_sec"] == RESTART_REGIME_CONFIRM_SECS
    assert RESTART_REGIME_CONFIRM_SECS < REGIME_CONFIRM_SECS


def test_candidate_age_wall_clock_progresses_despite_scan_delay():
    analyzer = MarketRegimeAnalyzer()
    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())

    analyzer._candidate_since -= 12

    assert analyzer.candidate_age_sec >= 12


def test_api_timeout_does_not_reset_candidate_regime():
    analyzer = MarketRegimeAnalyzer()
    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())

    analyzer.note_scan_stale("api_timeout")

    assert analyzer.to_dict()["candidate_regime"] == MarketRegime.KOSDAQ_NORMAL.value


def test_api_stall_state_after_consecutive_timeouts():
    analyzer = MarketRegimeAnalyzer()
    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())

    analyzer._last_valid_update_at = time.time() - API_STALL_SEC - 1

    assert analyzer.to_dict()["api_stall"] is True


def test_scan_zero_zero_does_not_reset_hysteresis():
    analyzer = MarketRegimeAnalyzer()
    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())
    before = analyzer._candidate_since

    analyzer.note_scan_stale("api_empty")

    assert analyzer._candidate_since == before
    assert analyzer.to_dict()["candidate_regime"] == MarketRegime.KOSDAQ_NORMAL.value


def test_candidate_regime_ttl():
    analyzer = MarketRegimeAnalyzer()
    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())

    analyzer._last_valid_update_at = time.time() - REGIME_CANDIDATE_TTL_SEC + 1
    analyzer.note_scan_stale("api_timeout")
    assert analyzer.to_dict()["candidate_regime"] == MarketRegime.KOSDAQ_NORMAL.value

    analyzer._last_valid_update_at = time.time() - REGIME_CANDIDATE_TTL_SEC - 1
    analyzer.note_scan_stale("api_timeout")
    assert analyzer.to_dict()["candidate_regime"] is None


def test_strategy_schedule_reason_regime_confirming():
    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._watchlist = {"A005930", "A000660"}
    bot._ws_symbols = ["A005930", "A000660"]
    bot._regime_analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())
    bot._position_mgr = MagicMock()
    bot._position_mgr.active_positions.return_value = {}
    bot._executor = MagicMock()
    bot._executor.active_order_nos.return_value = []

    snapshot = bot._strategy_schedule_snapshot(datetime(2026, 5, 8, 10, 30, 0))

    assert snapshot["active"] is False
    assert snapshot["block_reason"] == StrategyBlockReason.REGIME_CONFIRMING.value
    assert snapshot["reason"] == StrategyBlockReason.REGIME_CONFIRMING.value


def test_strategy_schedule_contains_diagnostics():
    bot = ScalpingBot()
    bot._status = BotStatus.RUNNING
    bot._watchlist = {"A005930"}
    bot._ws_symbols = ["A005930"]
    bot._regime_analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())
    bot._position_mgr = MagicMock()
    bot._position_mgr.active_positions.return_value = {}
    bot._executor = MagicMock()
    bot._executor.active_order_nos.return_value = []

    snapshot = bot._strategy_schedule_snapshot(datetime(2026, 5, 8, 10, 30, 0))

    assert "candidate_age_sec" in snapshot
    assert "confirm_required_sec" in snapshot
    assert "api_stall" in snapshot
    assert "watchlist_count" in snapshot
    assert snapshot["candidate_regime"] == MarketRegime.KOSDAQ_NORMAL.value


def test_signal_summary_no_entry_reason():
    engine = SignalEngine()
    symbol = "A005930"
    engine.register(symbol)
    engine.inject_vol_ratio(symbol, 3.0)
    engine.inject_atr_candles(symbol, [Candle(high=73_000, low=71_000, close=72_000)] * 14)
    engine.process_tick(_tick(symbol=symbol, price=72_000))

    summary = engine.signal_summary({symbol}, score_threshold=85.0)

    assert summary["watchlist"] == 1
    assert summary["entry_signal"] == 0
    assert "best_score" in summary
    assert "avg_score_gap" in summary
    assert "avg_exec_strength_gap" in summary
    assert "avg_vol_ratio_gap" in summary
    assert "avg_pullback_gap_pct" in summary
    assert summary["details"][0]["score_gap"] >= 0
    assert summary["details"][0]["exec_strength_gap"] >= 0
    assert summary["top_block"] in {
        "waiting_pullback",
        "breakout_not_confirmed",
        "vwap_not_ready",
        "score_below",
    }


def test_hard_no_trade_still_blocks_immediately():
    analyzer = MarketRegimeAnalyzer()
    analyzer._current_regime = MarketRegime.KOSDAQ_NORMAL

    regime, _ = analyzer.update(kosdaq_change_pct=-0.03, top_candidates=[])

    assert regime == MarketRegime.NO_TRADE
    assert analyzer.to_dict()["hard_no_trade"] is True


def test_restart_warmup_to_kosdaq_normal():
    analyzer = MarketRegimeAnalyzer()

    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())
    analyzer._candidate_since -= RESTART_REGIME_CONFIRM_SECS + 1
    analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())
    regime, _ = analyzer.update(kosdaq_change_pct=0.008, top_candidates=_normal_candidates())

    assert regime == MarketRegime.KOSDAQ_NORMAL


def test_strong_candidate_uses_30s_confirmation():
    analyzer = MarketRegimeAnalyzer()

    analyzer.update(kosdaq_change_pct=0.02, top_candidates=_aggressive_candidates())

    assert analyzer.to_dict()["confirm_required_sec"] == STRONG_REGIME_CONFIRM_SECS
