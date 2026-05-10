"""VWAP / ATR 계산기 — 순수 함수, 상태 없는 클래스, 완전 테스트 가능."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

from .constants import ATR_PERIOD, VWAP_WARMUP_MINUTES, BREAKOUT_CONFIRM_TICKS


class Candle(NamedTuple):
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class VWAPState:
    """당일 누적 VWAP. 틱마다 O(1) 업데이트.

    H0STCNT0의 ACML_VOL / ACML_TR_PBMN 을 그대로 쓰면
    누적 합산 없이 최신 필드 두 개만 보관하면 됨.
    직접 틱 price × vol 누산 방식도 지원 (update_tick).
    """

    _cum_pv: float = 0.0
    _cum_v:  float = 0.0
    _tick_count: int = 0   # VWAP 신뢰도용

    # ── KIS ACML 필드 직접 사용 (권장) ──────────────────────────────────────
    def update_acml(self, acml_tr_pbmn: float, acml_vol: float) -> None:
        """ACML_TR_PBMN(누적 거래대금), ACML_VOL(누적 거래량) 직접 설정."""
        self._cum_pv = acml_tr_pbmn
        self._cum_v  = acml_vol
        self._tick_count += 1

    # ── 틱별 누산 방식 (ACML 필드 없을 때) ──────────────────────────────────
    def update_tick(self, price: float, volume: float) -> None:
        self._cum_pv  += price * volume
        self._cum_v   += volume
        self._tick_count += 1

    @property
    def vwap(self) -> float:
        return self._cum_pv / self._cum_v if self._cum_v > 0 else 0.0

    def gap(self, price: float) -> float:
        """(price − VWAP) / VWAP. 양수 = VWAP 위."""
        v = self.vwap
        return (price - v) / v if v > 0 else 0.0

    @property
    def is_warmed_up(self) -> bool:
        """장 시작 후 약 10분(≈120 틱 이상) 경과 여부 — 틱 기반 근사."""
        return self._tick_count >= 120

    def reset(self) -> None:
        self._cum_pv = self._cum_v = 0.0
        self._tick_count = 0


@dataclass
class ATRState:
    """Wilder 방식 ATR. 분봉 캔들 완성 시 update_candle() 호출.

    장 시작 전 KIS get_intraday_bars() 결과를 bulk_load()로 주입하고
    장중에는 각 분봉 완성 시점에 update_candle()을 추가 호출.
    """

    period: int = ATR_PERIOD
    _trs:       deque = field(default_factory=lambda: deque(maxlen=ATR_PERIOD))
    _prev_close: float = 0.0
    _atr:       float = 0.0

    def update_candle(self, high: float, low: float, close: float) -> None:
        if self._prev_close <= 0.0:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low  - self._prev_close),
            )
        self._trs.append(tr)
        if len(self._trs) >= self.period:
            if self._atr <= 0.0:
                self._atr = sum(self._trs) / len(self._trs)
            else:
                # Wilder smoothing: EMA(1/period)
                self._atr = (self._atr * (self.period - 1) + tr) / self.period
        self._prev_close = close

    def bulk_load(self, candles: list[Candle]) -> None:
        """장 시작 전 과거 캔들 일괄 주입."""
        for c in candles:
            self.update_candle(c.high, c.low, c.close)

    @property
    def atr(self) -> float:
        return self._atr

    @property
    def ready(self) -> bool:
        return len(self._trs) >= self.period and self._atr > 0.0

    def reset(self) -> None:
        self._trs.clear()
        self._prev_close = 0.0
        self._atr = 0.0


@dataclass
class PullbackTracker:
    """종목별 눌림 상태 추적.

    상태 전이:
      IDLE → WATCHING (고점 등록) → PULLBACK (눌림 감지) → BREAKOUT (재돌파)
      언제든 IDLE로 리셋 가능 (만료, 과다 눌림, 장 시간 초과)
    """

    symbol: str
    _phase: str = "idle"                # "idle" | "watching" | "pullback" | "breakout"
    _high: float = 0.0                  # 눌림 시작 고점 (눌림 시작 직전 5분봉 고가)
    _high_ts: float = 0.0               # 고점 등록 epoch seconds
    _low_since_high: float = 0.0        # 고점 이후 최저가
    _breakout_confirm_count: int = 0    # 고점 초과 연속 틱 수 (허위 돌파 방지)

    def register_high(self, price: float, ts: float) -> None:
        """고점 등록 — 재돌파 기준점."""
        self._high = price
        self._high_ts = ts
        self._low_since_high = price
        self._phase = "watching"

    def update(self, price: float, ts: float, max_wait_secs: float) -> str:
        """틱 가격으로 상태 갱신. 반환값: 현재 phase."""
        if self._phase == "idle":
            return "idle"

        # 타임아웃
        if ts - self._high_ts > max_wait_secs:
            self.reset()
            return "idle"

        if price < self._low_since_high:
            self._low_since_high = price

        pullback_pct = (self._high - self._low_since_high) / self._high if self._high > 0 else 0.0

        if self._phase == "watching":
            from .constants import PULLBACK_MIN_PCT, PULLBACK_MAX_PCT
            if pullback_pct > PULLBACK_MAX_PCT:
                self.reset()
                return "idle"
            if pullback_pct >= PULLBACK_MIN_PCT:
                self._phase = "pullback"

        elif self._phase == "pullback":
            from .constants import PULLBACK_MAX_PCT
            if pullback_pct > PULLBACK_MAX_PCT:
                self.reset()
                return "idle"
            # 재돌파: BREAKOUT_CONFIRM_TICKS 연속으로 고점 초과해야 확정
            if price > self._high:
                self._breakout_confirm_count += 1
                if self._breakout_confirm_count >= BREAKOUT_CONFIRM_TICKS:
                    self._phase = "breakout"
                    return "breakout"
            else:
                self._breakout_confirm_count = 0  # 고점 아래로 내려오면 카운트 초기화

        elif self._phase == "breakout":
            return "breakout"

        return self._phase

    @property
    def high(self) -> float:
        return self._high

    @property
    def pullback_pct(self) -> float:
        if self._high <= 0:
            return 0.0
        return (self._high - self._low_since_high) / self._high

    @property
    def phase(self) -> str:
        return self._phase

    def reset(self) -> None:
        self._phase = "idle"
        self._high = self._high_ts = self._low_since_high = 0.0
        self._breakout_confirm_count = 0
