"""Market Regime Analyzer — 시장 상태 판단 + 전략 파라미터 동적 결정.

Layer 구조:
  LAYER 1: MarketRegimeAnalyzer.update()  — 시장 상태 판단
  LAYER 2: REGIME_POLICIES[regime]        — 레짐별 파라미터 오버라이드
  LAYER 3~5: MarketScanner / SignalEngine / OrderExecutor (기존 레이어)

레짐 전이 규칙:
  - 일반 전환: REGIME_CONFIRM_SECS(5분) 동안 새 레짐이 유지되어야 전환
  - 하드 NO_TRADE: KOSDAQ -1.5%, fake_ratio>70%, VI 과열 → 즉시 전환
  - 회복: NO_TRADE에서 복귀도 동일 확인 시간 적용
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .constants import (
    MIN_ENTRY_SCORE, BREAKOUT_CONFIRM_TICKS,
    MAX_SYMBOLS, MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE_PCT,
    MAX_ENTRY_SPREAD_PCT, ATR_TRAIL_MULTIPLIER,
    KOSDAQ_HALT_THRESHOLD,
    REGIME_CONFIRM_SECS, REGIME_SCORE_AGGRESSIVE, REGIME_SCORE_NORMAL,
    RESTART_REGIME_CONFIRM_SECS, STRONG_REGIME_CONFIRM_SECS,
    REGIME_CANDIDATE_MIN_UPDATES, REGIME_CANDIDATE_TTL_SEC,
    DATA_STALE_SEC, API_STALL_SEC,
    FAKE_BREAKOUT_NO_TRADE_THRESHOLD, FAKE_BREAKOUT_TIGHTEN_THRESHOLD,
    VI_DENSITY_NO_TRADE_COUNT, VI_DENSITY_WINDOW_SECS,
)

logger = logging.getLogger(__name__)

# ─── KOSPI 대형주 유니버스 (KOSPI_DEFENSIVE 모드에서 사용) ─────────────────────
KOSPI_LARGE_CAP_UNIVERSE: list[str] = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "005380",  # 현대차
    "000270",  # 기아
    "005490",  # POSCO홀딩스
    "207940",  # 삼성바이오로직스
    "068270",  # 셀트리온
    "105560",  # KB금융
    "055550",  # 신한지주
    "034020",  # 두산에너빌리티
    "042700",  # 한미반도체
    "267260",  # HD현대일렉트릭
    "012450",  # 한화에어로스페이스
    "047810",  # 한국항공우주
    "329180",  # HD현대중공업
    "035420",  # NAVER
    "051910",  # LG화학
    "006400",  # 삼성SDI
    "316140",  # 우리금융지주
    "003550",  # LG
]

# ─── 테마 키워드 매핑 ─────────────────────────────────────────────────────────
_THEME_KEYWORDS: dict[str, list[str]] = {
    "이차전지":   ["배터리", "전지", "이차전지", "양극재", "음극재", "전해질", "에코프로", "리튬"],
    "반도체":    ["반도체", "HBM", "파운드리", "팹리스", "메모리"],
    "전력인프라":  ["전력", "변압기", "전선", "LS", "일진", "효성"],
    "방산":      ["항공", "미사일", "방산", "한화", "LIG", "한국항공"],
    "바이오":    ["바이오", "제약", "의약", "셀트리온", "삼성바이오", "헬스케어"],
    "AI/데이터":  ["AI", "인공지능", "데이터센터", "서버", "클라우드"],
    "로봇":      ["로봇", "로보틱스", "자동화", "협동"],
}


def classify_theme(name: str) -> str:
    """종목명 키워드로 테마 분류 (간이 구현). 매칭 없으면 '기타'."""
    for theme, keywords in _THEME_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return theme
    return "기타"


# ─── 1. MarketRegime Enum ────────────────────────────────────────────────────

class MarketRegime(Enum):
    KOSDAQ_AGGRESSIVE = "kosdaq_aggressive"  # 강한 모멘텀 → 공격적 진입
    KOSDAQ_NORMAL     = "kosdaq_normal"      # 보통 장세 → 표준 + 방어 강화
    KOSPI_DEFENSIVE   = "kospi_defensive"    # KOSDAQ 부진 → KOSPI 대형주 방어
    NO_TRADE          = "no_trade"           # 거래 중단


class StrategyBlockReason(Enum):
    OK = "ok"
    HARD_NO_TRADE = "hard_no_trade"
    REGIME_CONFIRMING = "regime_confirming"
    DATA_NOT_READY = "data_not_ready"
    DATA_STALE = "data_stale"
    API_STALL = "api_stall"
    SIGNAL_WAITING = "signal_waiting"
    TIME_WINDOW_CLOSED = "time_window_closed"
    RISK_HALTED = "risk_halted"


# ─── 2. RegimeScore (점수 분해 + 원시 지표) ─────────────────────────────────

@dataclass
class RegimeScore:
    """시장 레짐 점수 분해 (총합 최대 100점)."""
    # 점수 구성요소
    kosdaq_index_score: float    # max 20 — KOSDAQ 지수 방향성
    top_momentum_score: float    # max 20 — 거래대금 상위 평균 등락률
    volume_surge_score: float    # max 15 — 거래량 급증 배율
    upper_limit_score: float     # max 10 — 상한가 종목 수
    theme_strength_score: float  # max 10 — 강한 테마 비율
    fake_breakout_score: float   # max 15 — fake breakout 낮을수록 높음
    spread_stability_score: float  # max 10 — 스프레드 안정성
    total: float                 # 합계 (0~100)

    # 원시 지표 (로그 / 백테스트 분석용)
    kosdaq_change_pct: float
    kospi_change_pct: float
    avg_top_change_pct: float
    avg_vol_ratio: float
    fake_breakout_ratio: float
    spread_avg: float
    vi_count_30m: int
    upper_limit_count: int
    candidate_count: int = 0

    # 결정된 레짐 (update() 후 채워짐)
    regime: MarketRegime = field(default=MarketRegime.NO_TRADE)

    def to_dict(self) -> dict:
        return {
            "regime":                self.regime.value,
            "total":                 round(self.total, 1),
            "kosdaq_index_score":    round(self.kosdaq_index_score, 1),
            "top_momentum_score":    round(self.top_momentum_score, 1),
            "volume_surge_score":    round(self.volume_surge_score, 1),
            "upper_limit_score":     round(self.upper_limit_score, 1),
            "theme_strength_score":  round(self.theme_strength_score, 1),
            "fake_breakout_score":   round(self.fake_breakout_score, 1),
            "spread_stability_score": round(self.spread_stability_score, 1),
            "kosdaq_change_pct":     round(self.kosdaq_change_pct * 100, 2),
            "kospi_change_pct":      round(self.kospi_change_pct * 100, 2),
            "avg_top_change_pct":    round(self.avg_top_change_pct * 100, 2),
            "avg_vol_ratio":         round(self.avg_vol_ratio, 2),
            "fake_breakout_ratio":   round(self.fake_breakout_ratio * 100, 1),
            "spread_avg_pct":        round(self.spread_avg * 100, 3),
            "vi_count_30m":          self.vi_count_30m,
            "upper_limit_count":     self.upper_limit_count,
        }


# ─── 3. RegimePolicy (레짐별 전략 파라미터) ──────────────────────────────────

@dataclass(frozen=True)
class RegimePolicy:
    """레짐별 전략 파라미터 오버라이드."""
    regime: MarketRegime
    min_entry_score: float         # 진입 최소 점수
    breakout_confirm_ticks: int    # 재돌파 확인 연속 틱 수
    max_symbols: int               # 동시 최대 보유 종목
    max_position_pct: float        # 종목당 최대 비중
    max_total_exposure_pct: float  # 전체 최대 노출
    max_entry_spread_pct: float    # 최대 허용 스프레드
    atr_trail_multiplier: float    # 트레일링 스탑 ATR 배수
    universe: str                  # "kosdaq_momentum" | "kosdaq_standard" | "kospi_large_cap"


REGIME_POLICIES: dict[MarketRegime, RegimePolicy] = {
    MarketRegime.KOSDAQ_AGGRESSIVE: RegimePolicy(
        regime=MarketRegime.KOSDAQ_AGGRESSIVE,
        min_entry_score=80.0,
        breakout_confirm_ticks=2,
        max_symbols=5,
        max_position_pct=0.20,
        max_total_exposure_pct=0.70,
        max_entry_spread_pct=0.003,
        atr_trail_multiplier=1.0,
        universe="kosdaq_momentum",
    ),
    MarketRegime.KOSDAQ_NORMAL: RegimePolicy(
        regime=MarketRegime.KOSDAQ_NORMAL,
        min_entry_score=85.0,
        breakout_confirm_ticks=3,
        max_symbols=3,
        max_position_pct=0.15,
        max_total_exposure_pct=0.50,
        max_entry_spread_pct=0.002,
        atr_trail_multiplier=0.8,
        universe="kosdaq_standard",
    ),
    MarketRegime.KOSPI_DEFENSIVE: RegimePolicy(
        regime=MarketRegime.KOSPI_DEFENSIVE,
        min_entry_score=90.0,
        breakout_confirm_ticks=3,
        max_symbols=2,
        max_position_pct=0.20,
        max_total_exposure_pct=0.40,
        max_entry_spread_pct=0.001,
        atr_trail_multiplier=0.6,
        universe="kospi_large_cap",
    ),
    MarketRegime.NO_TRADE: RegimePolicy(
        regime=MarketRegime.NO_TRADE,
        min_entry_score=9999.0,    # 사실상 진입 불가
        breakout_confirm_ticks=99,
        max_symbols=0,
        max_position_pct=0.0,
        max_total_exposure_pct=0.0,
        max_entry_spread_pct=0.0,
        atr_trail_multiplier=0.0,
        universe="none",
    ),
}


# ─── 4. MarketRegimeAnalyzer ─────────────────────────────────────────────────

class MarketRegimeAnalyzer:
    """
    역할:
    - KOSDAQ 모멘텀 점수 계산 (0~100)
    - Fake breakout ratio 추적 (최근 20개 돌파 결과 슬라이딩 윈도우)
    - VI 밀도 추적 (30분 슬라이딩 윈도우)
    - 스프레드 안정성 추적 (최근 30개 샘플)
    - 테마 집중도 분석 (키워드 기반 간이 분류)
    - 레짐 결정 + 히스테리시스 (5분 확인 후 전환)

    히스테리시스 정책:
    - 새 레짐 후보가 REGIME_CONFIRM_SECS 동안 지속될 때만 실제 전환
    - 하드 NO_TRADE 조건(KOSDAQ -1.5%, fake>70%, VI 과열) → 즉시 전환
    - 진입 요청 시 current_policy로 파라미터 오버라이드
    """

    def __init__(self) -> None:
        self._current_regime: MarketRegime = MarketRegime.NO_TRADE
        self._regime_since: float = time.monotonic()
        self._started_at: float = time.time()

        # 히스테리시스
        self._candidate_regime: Optional[MarketRegime] = None
        self._candidate_since: float = 0.0
        self._candidate_update_count: int = 0
        self._candidate_confirm_secs: int = REGIME_CONFIRM_SECS
        self._last_valid_update_at: float = 0.0
        self._last_hard_no_trade: bool = False

        # 추적 윈도우
        self._breakout_results: deque[bool] = deque(maxlen=20)
        self._spread_samples:   deque[float] = deque(maxlen=30)
        self._vi_timestamps:    deque[float] = deque()  # 30분 슬라이딩

        # 마지막 계산 결과 (외부 조회용)
        self._last_score: Optional[RegimeScore] = None

    # ── 외부 이벤트 기록 ─────────────────────────────────────────────────────

    def record_breakout_result(self, success: bool) -> None:
        """진입 결과 기록 (익절 close=True, 손절=False). fake breakout ratio 계산에 사용."""
        self._breakout_results.append(success)

    def record_spread(self, spread_pct: float) -> None:
        """스프레드 샘플 기록."""
        if spread_pct > 0:
            self._spread_samples.append(spread_pct)

    def record_vi(self) -> None:
        """VI 발동 기록 (30분 윈도우 유지)."""
        now = time.monotonic()
        self._vi_timestamps.append(now)
        self._prune_vi_window(now)

    def check_hard_no_trade(self, kosdaq_change_pct: float) -> bool:
        """
        BUG-38 FIX: 스캔 윈도우(10:30) 이후에도 하드 NO_TRADE 조건 즉시 평가.
        True이면 regime을 NO_TRADE로 즉시 전환.
        """
        self._prune_vi_window(time.monotonic())
        fb_ratio = self.fake_breakout_ratio
        vi_count = len(self._vi_timestamps)

        is_hard = (
            kosdaq_change_pct <= KOSDAQ_HALT_THRESHOLD
            or (fb_ratio > FAKE_BREAKOUT_NO_TRADE_THRESHOLD and len(self._breakout_results) >= 10)
            or vi_count >= VI_DENSITY_NO_TRADE_COUNT
        )
        if is_hard and self._current_regime != MarketRegime.NO_TRADE:
            logger.warning(
                "Hard NO_TRADE (post-scan): kosdaq=%.2f%% fb=%.0f%% vi=%d",
                kosdaq_change_pct * 100, fb_ratio * 100, vi_count,
            )
            self._current_regime = MarketRegime.NO_TRADE
            self._regime_since = time.monotonic()
            self._candidate_regime = None
            self._candidate_update_count = 0
        self._last_hard_no_trade = is_hard
        return is_hard

    # ── 메인 업데이트 ────────────────────────────────────────────────────────

    def update(
        self,
        kosdaq_change_pct: float,
        top_candidates: list,          # list[SymbolCandidate] — 타입 힌트 순환 방지
        kospi_change_pct: float = 0.0,
    ) -> tuple[MarketRegime, RegimeScore]:
        """
        레짐 갱신. _scan_loop에서 3초마다 호출.
        반환: (current_regime, score)
        """
        score = self._compute_score(kosdaq_change_pct, top_candidates, kospi_change_pct)
        new_regime = self._decide_regime(score, kospi_change_pct)
        self._last_valid_update_at = time.time()
        self._apply_hysteresis(new_regime, score)
        score.regime = self._current_regime
        self._last_score = score
        return self._current_regime, score

    def note_scan_stale(self, source_status: str = "api_empty") -> None:
        """스캔 실패/0건을 기록하되 후보 레짐은 TTL 안에서 유지한다."""
        now = time.time()
        if (
            self._candidate_regime
            and self._last_valid_update_at > 0
            and now - self._last_valid_update_at > REGIME_CANDIDATE_TTL_SEC
        ):
            self._candidate_regime = None
            self._candidate_update_count = 0

    # ── 조회 ─────────────────────────────────────────────────────────────────

    @property
    def current_regime(self) -> MarketRegime:
        return self._current_regime

    @property
    def current_policy(self) -> RegimePolicy:
        return REGIME_POLICIES[self._current_regime]

    @property
    def last_score(self) -> Optional[RegimeScore]:
        return self._last_score

    @property
    def fake_breakout_ratio(self) -> float:
        n = len(self._breakout_results)
        if n < 5:
            return 0.0
        return 1.0 - sum(self._breakout_results) / n

    def to_dict(self) -> dict:
        s = self._last_score
        elapsed = int(time.monotonic() - self._regime_since)
        return {
            "regime":            self._current_regime.value,
            "regime_since_secs": elapsed,
            "candidate_regime":  self._candidate_regime.value if self._candidate_regime else None,
            "candidate_age_sec": self.candidate_age_sec,
            "candidate_updates": self._candidate_update_count,
            "confirm_required_sec": self._candidate_confirm_secs,
            "confirm_remaining_sec": max(0, self._candidate_confirm_secs - self.candidate_age_sec),
            "hard_no_trade": self._last_hard_no_trade,
            "last_valid_update_age_sec": self.last_valid_update_age_sec,
            "api_stall": self.is_api_stall,
            "data_stale": self.is_data_stale,
            "score":             round(s.total, 1) if s else 0.0,
            "fake_breakout_ratio": round(self.fake_breakout_ratio, 3),
            "vi_count_30m":      s.vi_count_30m if s else 0,
            "spread_avg_pct":    round((s.spread_avg if s else 0.0) * 100, 3),
            "kosdaq_change_pct": round((s.kosdaq_change_pct if s else 0.0) * 100, 2),
            "avg_top_change_pct": round((s.avg_top_change_pct if s else 0.0) * 100, 2),
        }

    @property
    def candidate_age_sec(self) -> int:
        if not self._candidate_regime or self._candidate_since <= 0:
            return 0
        return max(0, int(time.time() - self._candidate_since))

    @property
    def last_valid_update_age_sec(self) -> int:
        if self._last_valid_update_at <= 0:
            return 999999
        return max(0, int(time.time() - self._last_valid_update_at))

    @property
    def is_data_stale(self) -> bool:
        return self.last_valid_update_age_sec >= DATA_STALE_SEC

    @property
    def is_api_stall(self) -> bool:
        return self.last_valid_update_age_sec >= API_STALL_SEC

    # ── 내부: 점수 계산 ──────────────────────────────────────────────────────

    def _compute_score(
        self,
        kosdaq_change_pct: float,
        top_candidates: list,
        kospi_change_pct: float,
    ) -> RegimeScore:
        n = len(top_candidates)

        # 1. KOSDAQ 지수 방향성 (max 20)
        if kosdaq_change_pct >= 0.015:
            idx_score = 20.0
        elif kosdaq_change_pct >= 0.010:
            idx_score = 16.0
        elif kosdaq_change_pct >= 0.005:
            idx_score = 10.0
        elif kosdaq_change_pct >= 0.0:
            idx_score = 4.0
        else:
            idx_score = 0.0

        # 2. 거래대금 상위 평균 등락률 (max 20)
        avg_change = sum(c.change_pct for c in top_candidates) / n if n else 0.0
        if avg_change >= 0.07:
            top_score = 20.0
        elif avg_change >= 0.05:
            top_score = 14.0
        elif avg_change >= 0.03:
            top_score = 7.0
        elif avg_change >= 0.01:
            top_score = 2.0
        else:
            top_score = 0.0

        # 3. 거래량 급증 배율 (max 15)
        avg_vol = sum(c.vol_ratio for c in top_candidates) / n if n else 0.0
        if avg_vol >= 4.0:
            vol_score = 15.0
        elif avg_vol >= 3.0:
            vol_score = 11.0
        elif avg_vol >= 2.0:
            vol_score = 6.0
        elif avg_vol >= 1.5:
            vol_score = 2.0
        else:
            vol_score = 0.0

        # 4. 상한가 종목 수 (max 10)
        upper_count = sum(1 for c in top_candidates if c.change_pct >= 0.29)
        if upper_count >= 3:
            up_score = 10.0
        elif upper_count >= 2:
            up_score = 7.0
        elif upper_count >= 1:
            up_score = 4.0
        else:
            up_score = 0.0

        # 5. 테마 강도 (max 10): 상위 종목 중 +5% 이상 비율
        strong = sum(1 for c in top_candidates if c.change_pct >= 0.05) if n else 0
        theme_score = min(strong / max(n, 1) * 20.0, 10.0)

        # 6. Fake breakout 안정성 (max 15): 비율 낮을수록 높은 점수
        fb_ratio = self.fake_breakout_ratio
        n_samples = len(self._breakout_results)
        if n_samples < 5:
            fb_score = 7.5      # 데이터 부족: 중립
        elif fb_ratio <= 0.20:
            fb_score = 15.0
        elif fb_ratio <= 0.35:
            fb_score = 11.0
        elif fb_ratio <= 0.50:
            fb_score = 6.0
        elif fb_ratio <= 0.65:
            fb_score = 2.0
        else:
            fb_score = 0.0

        # 7. 스프레드 안정성 (max 10)
        avg_spread = (
            sum(self._spread_samples) / len(self._spread_samples)
            if self._spread_samples else 0.002   # 데이터 없으면 중립
        )
        if avg_spread <= 0.001:
            sp_score = 10.0
        elif avg_spread <= 0.0015:
            sp_score = 7.0
        elif avg_spread <= 0.002:
            sp_score = 4.0
        elif avg_spread <= 0.003:
            sp_score = 1.0
        else:
            sp_score = 0.0

        total = idx_score + top_score + vol_score + up_score + theme_score + fb_score + sp_score

        # VI 밀도 조회 (30분 윈도우)
        now = time.monotonic()
        self._prune_vi_window(now)
        vi_count = len(self._vi_timestamps)

        return RegimeScore(
            kosdaq_index_score=idx_score,
            top_momentum_score=top_score,
            volume_surge_score=vol_score,
            upper_limit_score=up_score,
            theme_strength_score=theme_score,
            fake_breakout_score=fb_score,
            spread_stability_score=sp_score,
            total=total,
            kosdaq_change_pct=kosdaq_change_pct,
            kospi_change_pct=kospi_change_pct,
            avg_top_change_pct=avg_change,
            avg_vol_ratio=avg_vol,
            fake_breakout_ratio=fb_ratio,
            spread_avg=avg_spread,
            vi_count_30m=vi_count,
            upper_limit_count=upper_count,
            candidate_count=n,
        )

    # ── 내부: 레짐 결정 ──────────────────────────────────────────────────────

    def _decide_regime(self, score: RegimeScore, kospi_change_pct: float) -> MarketRegime:
        """점수 + 하드 조건으로 다음 레짐 결정."""
        # ─ 하드 NO_TRADE (점수 무관하게 즉시 차단) ─
        if score.kosdaq_change_pct <= KOSDAQ_HALT_THRESHOLD:
            return MarketRegime.NO_TRADE
        if (score.fake_breakout_ratio > FAKE_BREAKOUT_NO_TRADE_THRESHOLD
                and len(self._breakout_results) >= 10):
            return MarketRegime.NO_TRADE
        if score.vi_count_30m >= VI_DENSITY_NO_TRADE_COUNT:
            return MarketRegime.NO_TRADE

        # ─ 소프트 등급 결정 ─
        if score.total >= REGIME_SCORE_AGGRESSIVE:
            # fake breakout이 높으면 aggressive 허용 안 함
            if score.fake_breakout_ratio > FAKE_BREAKOUT_TIGHTEN_THRESHOLD:
                return MarketRegime.KOSDAQ_NORMAL
            return MarketRegime.KOSDAQ_AGGRESSIVE

        if score.total >= REGIME_SCORE_NORMAL:
            return MarketRegime.KOSDAQ_NORMAL

        # KOSPI가 KOSDAQ보다 강하면 defensive 전환
        if kospi_change_pct > score.kosdaq_change_pct and kospi_change_pct >= 0.0:
            return MarketRegime.KOSPI_DEFENSIVE

        return MarketRegime.NO_TRADE

    # ── 내부: 히스테리시스 ───────────────────────────────────────────────────

    def _is_hard_no_trade(self, score: RegimeScore) -> bool:
        return (
            score.kosdaq_change_pct <= KOSDAQ_HALT_THRESHOLD
            or (score.fake_breakout_ratio > FAKE_BREAKOUT_NO_TRADE_THRESHOLD
                and len(self._breakout_results) >= 10)
            or score.vi_count_30m >= VI_DENSITY_NO_TRADE_COUNT
        )

    def _apply_hysteresis(self, new_regime: MarketRegime, score: RegimeScore) -> None:
        now_mono = time.monotonic()
        now_wall = time.time()
        self._last_hard_no_trade = self._is_hard_no_trade(score)

        # 하드 NO_TRADE → 즉시 전환 (히스테리시스 없음)
        if self._last_hard_no_trade and self._current_regime != MarketRegime.NO_TRADE:
            logger.warning(
                "Regime: IMMEDIATE→NO_TRADE. kosdaq=%.2f%% fb=%.0f%% vi=%d",
                score.kosdaq_change_pct * 100,
                score.fake_breakout_ratio * 100,
                score.vi_count_30m,
            )
            self._current_regime = MarketRegime.NO_TRADE
            self._regime_since = now_mono
            self._candidate_regime = None
            self._candidate_update_count = 0
            return

        if new_regime == self._current_regime:
            self._candidate_regime = None
            self._candidate_update_count = 0
            return

        # 후보 레짐 누적
        if self._candidate_regime != new_regime:
            self._candidate_regime = new_regime
            self._candidate_since = now_wall
            self._candidate_update_count = 1
            self._candidate_confirm_secs = self._confirm_secs_for(score)
            logger.info(
                "Regime candidate: %s→%s (score=%.0f count=%d confirm=%ds reason=%s)",
                self._current_regime.value, new_regime.value, score.total,
                self._candidate_update_count, self._candidate_confirm_secs,
                self._confirm_reason(score),
            )
            return
        self._candidate_update_count += 1
        self._candidate_confirm_secs = self._confirm_secs_for(score)

        # 확인 시간 경과 → 실제 전환
        if (
            now_wall - self._candidate_since >= self._candidate_confirm_secs
            and self._candidate_update_count >= REGIME_CANDIDATE_MIN_UPDATES
        ):
            old = self._current_regime
            self._current_regime = new_regime
            self._regime_since = now_mono
            self._candidate_regime = None
            self._candidate_update_count = 0
            logger.info(
                "Regime: %s→%s (score=%.0f fb=%.0f%% vi=%d spread=%.3f%% confirm=%ds)",
                old.value, new_regime.value,
                score.total,
                score.fake_breakout_ratio * 100,
                score.vi_count_30m,
                score.spread_avg * 100,
                self._candidate_confirm_secs,
            )

    def _confirm_secs_for(self, score: RegimeScore) -> int:
        if self._last_hard_no_trade:
            return REGIME_CONFIRM_SECS
        candidate_count = int(getattr(score, "candidate_count", 0) or 0)
        if score.total >= REGIME_SCORE_AGGRESSIVE and candidate_count >= 5:
            return STRONG_REGIME_CONFIRM_SECS
        if self._current_regime == MarketRegime.NO_TRADE and score.total >= 50 and candidate_count >= 5:
            return RESTART_REGIME_CONFIRM_SECS
        return REGIME_CONFIRM_SECS

    def _confirm_reason(self, score: RegimeScore) -> str:
        confirm = self._confirm_secs_for(score)
        if confirm == STRONG_REGIME_CONFIRM_SECS:
            return "strong_candidate"
        if confirm == RESTART_REGIME_CONFIRM_SECS:
            return "restart_warmup"
        return "default"

    # ── 내부: 유틸 ───────────────────────────────────────────────────────────

    def _prune_vi_window(self, now: float) -> None:
        """30분 이상 경과한 VI 기록 제거."""
        while self._vi_timestamps and now - self._vi_timestamps[0] > VI_DENSITY_WINDOW_SECS:
            self._vi_timestamps.popleft()
