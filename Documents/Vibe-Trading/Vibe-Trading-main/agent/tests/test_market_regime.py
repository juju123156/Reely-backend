"""Market Regime Analyzer 테스트."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.trading.scalping.market_regime import (
    MarketRegime, MarketRegimeAnalyzer, RegimePolicy, REGIME_POLICIES,
    classify_theme, KOSPI_LARGE_CAP_UNIVERSE,
)
from src.trading.scalping.constants import (
    REGIME_SCORE_AGGRESSIVE, REGIME_SCORE_NORMAL,
    FAKE_BREAKOUT_NO_TRADE_THRESHOLD, VI_DENSITY_NO_TRADE_COUNT,
    KOSDAQ_HALT_THRESHOLD,
)


# ── 1. 레짐 정책 정합성 ──────────────────────────────────────────────────────

def test_all_regimes_have_policy():
    for regime in MarketRegime:
        assert regime in REGIME_POLICIES


def test_policy_score_order():
    """AGGRESSIVE < NORMAL < DEFENSIVE < NO_TRADE 순으로 min_entry_score 높아짐."""
    agg  = REGIME_POLICIES[MarketRegime.KOSDAQ_AGGRESSIVE].min_entry_score
    norm = REGIME_POLICIES[MarketRegime.KOSDAQ_NORMAL].min_entry_score
    defe = REGIME_POLICIES[MarketRegime.KOSPI_DEFENSIVE].min_entry_score
    no   = REGIME_POLICIES[MarketRegime.NO_TRADE].min_entry_score
    assert agg <= norm <= defe < no


def test_policy_max_symbols_order():
    """AGGRESSIVE >= NORMAL >= DEFENSIVE > NO_TRADE."""
    agg  = REGIME_POLICIES[MarketRegime.KOSDAQ_AGGRESSIVE].max_symbols
    norm = REGIME_POLICIES[MarketRegime.KOSDAQ_NORMAL].max_symbols
    defe = REGIME_POLICIES[MarketRegime.KOSPI_DEFENSIVE].max_symbols
    no   = REGIME_POLICIES[MarketRegime.NO_TRADE].max_symbols
    assert agg >= norm >= defe > no


def test_no_trade_policy_blocks_all():
    p = REGIME_POLICIES[MarketRegime.NO_TRADE]
    assert p.min_entry_score > 9000
    assert p.max_symbols == 0
    assert p.max_total_exposure_pct == 0.0


def test_kospi_defensive_low_spread():
    """KOSPI defensive 스프레드 허용치가 가장 엄격."""
    p_defe = REGIME_POLICIES[MarketRegime.KOSPI_DEFENSIVE]
    p_agg  = REGIME_POLICIES[MarketRegime.KOSDAQ_AGGRESSIVE]
    assert p_defe.max_entry_spread_pct < p_agg.max_entry_spread_pct


# ── 2. 레짐 결정 로직 ───────────────────────────────────────────────────────

def _make_analyzer() -> MarketRegimeAnalyzer:
    return MarketRegimeAnalyzer()


def _make_candidate(change_pct: float = 0.05, vol_ratio: float = 3.0) -> MagicMock:
    c = MagicMock()
    c.change_pct = change_pct
    c.vol_ratio = vol_ratio
    return c


def test_no_trade_when_kosdaq_below_halt():
    """KOSDAQ 지수 -1.5% 이하 → 즉시 NO_TRADE."""
    a = _make_analyzer()
    # 먼저 aggressive 상태로 만들기
    regime, _ = a.update(kosdaq_change_pct=0.02, top_candidates=[_make_candidate(0.07)] * 10)
    # KOSDAQ 급락
    regime, score = a.update(
        kosdaq_change_pct=KOSDAQ_HALT_THRESHOLD - 0.001,
        top_candidates=[],
    )
    assert regime == MarketRegime.NO_TRADE


def test_no_trade_when_fake_breakout_high():
    """fake breakout 70% 초과 (샘플 10개 이상) → NO_TRADE."""
    a = _make_analyzer()
    for _ in range(10):
        a.record_breakout_result(False)   # 10번 실패
    regime, score = a.update(kosdaq_change_pct=0.01, top_candidates=[_make_candidate()] * 5)
    assert regime == MarketRegime.NO_TRADE
    assert score.fake_breakout_ratio > FAKE_BREAKOUT_NO_TRADE_THRESHOLD


def test_no_trade_when_vi_density_high():
    """30분 내 VI 10회 이상 → NO_TRADE."""
    a = _make_analyzer()
    for _ in range(VI_DENSITY_NO_TRADE_COUNT):
        a.record_vi()
    regime, score = a.update(kosdaq_change_pct=0.01, top_candidates=[_make_candidate()] * 5)
    assert regime == MarketRegime.NO_TRADE
    assert score.vi_count_30m >= VI_DENSITY_NO_TRADE_COUNT


def test_aggressive_when_high_score():
    """점수 70 이상 + fake breakout 낮음 → AGGRESSIVE (히스테리시스 확인 후)."""
    a = _make_analyzer()
    # 성공 기록으로 fb 낮게 유지
    for _ in range(10):
        a.record_breakout_result(True)
    for _ in range(10):
        a.record_spread(0.0008)

    # 히스테리시스로 바로 전환 안 됨 — 후보로 등록
    candidates = [_make_candidate(change_pct=0.08, vol_ratio=4.5)] * 15
    regime, score = a.update(kosdaq_change_pct=0.02, top_candidates=candidates)
    # 아직 NO_TRADE (기본값) — 후보 전환 대기 중
    assert score.total >= REGIME_SCORE_AGGRESSIVE
    assert a._candidate_regime == MarketRegime.KOSDAQ_AGGRESSIVE


def test_normal_when_medium_score():
    """점수 40~69 → KOSDAQ_NORMAL 후보 등록."""
    a = _make_analyzer()
    for _ in range(5):
        a.record_breakout_result(True)
    candidates = [_make_candidate(change_pct=0.04, vol_ratio=2.0)] * 10
    regime, score = a.update(kosdaq_change_pct=0.008, top_candidates=candidates)
    assert REGIME_SCORE_NORMAL <= score.total < REGIME_SCORE_AGGRESSIVE
    assert a._candidate_regime == MarketRegime.KOSDAQ_NORMAL


def test_kospi_defensive_when_kospi_stronger():
    """KOSPI 등락률 > KOSDAQ 등락률 이고 둘 다 양수 → KOSPI_DEFENSIVE 후보."""
    a = _make_analyzer()
    candidates = [_make_candidate(change_pct=0.01, vol_ratio=1.0)] * 3
    regime, score = a.update(
        kosdaq_change_pct=0.003,
        top_candidates=candidates,
        kospi_change_pct=0.01,  # KOSPI가 강함
    )
    assert a._candidate_regime == MarketRegime.KOSPI_DEFENSIVE


# ── 3. 히스테리시스 ──────────────────────────────────────────────────────────

def test_hysteresis_prevents_immediate_switch():
    """강한 장세여도 REGIME_CONFIRM_SECS 경과 전에는 전환 안 됨."""
    a = _make_analyzer()
    for _ in range(10):
        a.record_breakout_result(True)
    for _ in range(10):
        a.record_spread(0.0008)

    candidates = [_make_candidate(change_pct=0.08, vol_ratio=5.0)] * 15
    regime, _ = a.update(kosdaq_change_pct=0.02, top_candidates=candidates)

    # 바로는 NO_TRADE (기본값) 유지
    assert regime == MarketRegime.NO_TRADE
    assert a._candidate_regime is not None


def test_hard_no_trade_is_immediate():
    """하드 NO_TRADE 조건은 히스테리시스 없이 즉시 전환."""
    a = _make_analyzer()
    # 먼저 후보 상태 만들기
    candidates = [_make_candidate(change_pct=0.08, vol_ratio=5.0)] * 10
    a.update(kosdaq_change_pct=0.02, top_candidates=candidates)
    # 강제로 current를 바꾸어 hard 조건 확인
    a._current_regime = MarketRegime.KOSDAQ_NORMAL

    for _ in range(10):
        a.record_breakout_result(False)

    regime, _ = a.update(kosdaq_change_pct=0.01, top_candidates=[_make_candidate()] * 5)
    assert regime == MarketRegime.NO_TRADE


# ── 4. 점수 계산 ─────────────────────────────────────────────────────────────

def test_score_max_achievable():
    """이상적인 조건에서 점수가 AGGRESSIVE 기준 이상."""
    a = _make_analyzer()
    for _ in range(10):
        a.record_breakout_result(True)
    for _ in range(20):
        a.record_spread(0.0005)

    big_candidates = [_make_candidate(change_pct=0.10, vol_ratio=5.0)] * 20
    _, score = a.update(kosdaq_change_pct=0.02, top_candidates=big_candidates)
    assert score.total >= REGIME_SCORE_AGGRESSIVE


def test_score_zero_market():
    """하락장 + 거래 없으면 0에 가까운 점수."""
    a = _make_analyzer()
    _, score = a.update(kosdaq_change_pct=-0.02, top_candidates=[])
    assert score.kosdaq_index_score == 0.0
    assert score.top_momentum_score == 0.0
    assert score.volume_surge_score == 0.0


def test_fake_breakout_ratio_tracked():
    """기록된 실패 비율이 점수에 반영된다."""
    a = _make_analyzer()
    for _ in range(3):
        a.record_breakout_result(True)
    for _ in range(7):
        a.record_breakout_result(False)  # 70% 실패

    assert abs(a.fake_breakout_ratio - 0.7) < 0.01


def test_spread_neutral_when_no_samples():
    """스프레드 샘플 없으면 중립값으로 처리."""
    a = _make_analyzer()
    _, score = a.update(kosdaq_change_pct=0.01, top_candidates=[_make_candidate()] * 5)
    assert score.spread_stability_score > 0   # 중립 = 일부 점수 존재


# ── 5. VI 밀도 슬라이딩 윈도우 ───────────────────────────────────────────────

def test_vi_window_prunes_old():
    """30분 이전 VI는 카운트에서 제외."""
    a = _make_analyzer()
    old_ts = time.monotonic() - 2000
    for _ in range(5):
        a._vi_timestamps.append(old_ts)
    a.record_vi()   # 최신 1개 추가

    _, score = a.update(kosdaq_change_pct=0.01, top_candidates=[])
    assert score.vi_count_30m == 1   # 오래된 5개는 pruned


# ── 6. 테마 분류 ─────────────────────────────────────────────────────────────

def test_theme_classification():
    assert classify_theme("에코프로비엠") == "이차전지"
    assert classify_theme("한화에어로스페이스") == "방산"
    assert classify_theme("셀트리온헬스케어") == "바이오"
    assert classify_theme("현대로보틱스") == "로봇"
    assert classify_theme("알수없는회사") == "기타"


# ── 7. KOSPI 유니버스 ────────────────────────────────────────────────────────

def test_kospi_universe_not_empty():
    assert len(KOSPI_LARGE_CAP_UNIVERSE) >= 10


def test_kospi_universe_samsung_included():
    assert "005930" in KOSPI_LARGE_CAP_UNIVERSE   # 삼성전자


# ── 8. to_dict / RegimeScore.to_dict ────────────────────────────────────────

def test_to_dict_keys():
    a = _make_analyzer()
    _, score = a.update(kosdaq_change_pct=0.01, top_candidates=[_make_candidate()] * 5)
    d = a.to_dict()
    assert "regime" in d
    assert "score" in d
    assert "fake_breakout_ratio" in d
    assert "vi_count_30m" in d


def test_score_to_dict_keys():
    a = _make_analyzer()
    _, score = a.update(kosdaq_change_pct=0.01, top_candidates=[_make_candidate()] * 5)
    sd = score.to_dict()
    assert "regime" in sd
    assert "total" in sd
    assert "fake_breakout_ratio" in sd
    assert "spread_avg_pct" in sd
