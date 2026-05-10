"""KR 단타 수급 판단 엔진 — 추매 / 매도 신호.

설계 원칙 (레이턴시 최소화):
  - 모든 지표 계산은 O(1) — deque 링 버퍼 + 누적합 유지
  - 핫패스에 pandas/numpy 없음 — 순수 float 연산
  - __slots__ 으로 속성 접근 속도 향상
  - 외부에서 poll 할 때마다 update_poll() 한 번만 호출

지표:
  체결강도   = (매수체결량 합 / 매도체결량 합) × 100
  호가잔량비  = 매수잔량 합 / 매도잔량 합
  거래량배율  = 최근 틱 거래량 / 진입 시점 기준 평균 거래량

추매 조건 (3개 동시):
  체결강도 > 130  AND  호가잔량비 > 1.5  AND  거래량배율 > 1.5
  AND 미실현수익 > +0.5%

매도 조건 (1개라도):
  체결강도 < 70        → 수급 이탈
  호가잔량비 < 0.7     → 호가 반전
  거래량배율 > 3.0 AND 직전 고점 미갱신  → 클라이맥스 소진
"""

from __future__ import annotations

from collections import deque
from typing import NamedTuple


class OrderFlowSignal(NamedTuple):
    action: str          # "pyramid" | "exit" | "hold"
    reason: str
    exec_strength: float  # 체결강도
    ob_imbalance: float   # 호가잔량비
    vol_ratio: float      # 거래량배율


class OrderFlowState:
    """종목 1개의 수급 상태를 추적하는 경량 상태 머신."""

    __slots__ = (
        "_window",
        "_pyramid_es_min", "_pyramid_ob_min", "_pyramid_vol_min", "_pyramid_pnl_min",
        "_exit_es_max", "_exit_ob_max", "_exit_vol_climax",
        "_buy_vols", "_sell_vols", "_prices",
        "_buy_sum", "_sell_sum",
        "_prev_buy_total", "_prev_sell_total",
        "_baseline_vol", "_baseline_count", "_baseline_sum",
        "_session_high",
        "_bid_qty", "_ask_qty",
    )

    def __init__(
        self,
        window: int = 20,
        *,
        pyramid_es_min: float = 130.0,
        pyramid_ob_min: float = 1.5,
        pyramid_vol_min: float = 1.5,
        pyramid_pnl_min: float = 0.005,
        exit_es_max: float = 70.0,
        exit_ob_max: float = 0.7,
        exit_vol_climax: float = 3.0,
    ) -> None:
        self._window = window
        self._pyramid_es_min = pyramid_es_min
        self._pyramid_ob_min = pyramid_ob_min
        self._pyramid_vol_min = pyramid_vol_min
        self._pyramid_pnl_min = pyramid_pnl_min
        self._exit_es_max = exit_es_max
        self._exit_ob_max = exit_ob_max
        self._exit_vol_climax = exit_vol_climax

        self._buy_vols: deque[float] = deque(maxlen=window)
        self._sell_vols: deque[float] = deque(maxlen=window)
        self._prices: deque[float] = deque(maxlen=window)

        self._buy_sum = 0.0
        self._sell_sum = 0.0

        # KIS REST는 누적값을 주므로 직전 누적값 저장 후 델타 계산
        self._prev_buy_total = 0.0
        self._prev_sell_total = 0.0

        # 진입 시점 기준 거래량 (baseline 설정 전까지 수집)
        self._baseline_vol = 0.0
        self._baseline_count = 0
        self._baseline_sum = 0.0

        self._session_high = 0.0
        self._bid_qty = 0.0
        self._ask_qty = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_baseline(self) -> None:
        """포지션 진입 시점에 호출 — 이후 거래량 배율 계산의 기준이 됨."""
        if self._baseline_count > 0:
            self._baseline_vol = self._baseline_sum / self._baseline_count
        if self._prices:
            self._session_high = max(self._prices)

    def update_poll(
        self,
        *,
        price: float,
        buy_vol_total: float,   # KIS shnu_cntg_smtn (누적 매수체결량)
        sell_vol_total: float,  # KIS seln_cntg_smtn (누적 매도체결량)
        bid_qty: float = 0.0,   # KIS total_bidp_rsqn (총 매수호가 잔량)
        ask_qty: float = 0.0,   # KIS total_askp_rsqn (총 매도호가 잔량)
    ) -> None:
        """폴링 1회에 1번 호출. 누적값 → 델타 변환 후 링버퍼 갱신. O(1)."""
        # 누적값 → 이번 폴링 구간 델타
        buy_delta = max(buy_vol_total - self._prev_buy_total, 0.0)
        sell_delta = max(sell_vol_total - self._prev_sell_total, 0.0)
        self._prev_buy_total = buy_vol_total
        self._prev_sell_total = sell_vol_total

        # 링버퍼 갱신 (꽉 차면 맨 앞 값이 자동으로 빠짐)
        if len(self._buy_vols) == self._window:
            self._buy_sum -= self._buy_vols[0]
            self._sell_sum -= self._sell_vols[0]

        self._buy_vols.append(buy_delta)
        self._sell_vols.append(sell_delta)
        self._prices.append(price)

        self._buy_sum += buy_delta
        self._sell_sum += sell_delta

        # baseline 수집 (set_baseline 호출 전까지)
        tick_vol = buy_delta + sell_delta
        if tick_vol > 0:
            self._baseline_sum += tick_vol
            self._baseline_count += 1

        # 호가 갱신
        if bid_qty > 0:
            self._bid_qty = bid_qty
        if ask_qty > 0:
            self._ask_qty = ask_qty

        # 당일 고점 갱신
        if price > self._session_high:
            self._session_high = price

    def exec_strength(self) -> float:
        """체결강도 = (매수체결량 합 / 매도체결량 합) × 100. O(1)."""
        if self._sell_sum < 1e-9:
            return 100.0
        return (self._buy_sum / self._sell_sum) * 100.0

    def ob_imbalance(self) -> float:
        """호가잔량비 = 매수잔량 합 / 매도잔량 합. O(1)."""
        if self._ask_qty < 1e-9:
            return 1.0
        return self._bid_qty / self._ask_qty

    def vol_ratio(self) -> float:
        """최근 폴링 거래량 / 진입기준 평균 거래량. O(1)."""
        if self._baseline_vol < 1e-9 or not self._buy_vols:
            return 1.0
        recent = self._buy_vols[-1] + self._sell_vols[-1]
        return recent / self._baseline_vol

    def evaluate(self, *, in_position: bool, unrealized_pnl: float = 0.0) -> OrderFlowSignal:
        """현재 수급 상태를 평가해 신호를 반환. O(1)."""
        es = self.exec_strength()
        obi = self.ob_imbalance()
        vr = self.vol_ratio()

        if in_position:
            # --- 매도 조건 (하나라도 충족 시 즉시 exit) ---
            if es < self._exit_es_max:
                return OrderFlowSignal(
                    "exit", f"체결강도 이탈 ({es:.0f} < {self._exit_es_max})", es, obi, vr
                )
            if obi < self._exit_ob_max:
                return OrderFlowSignal(
                    "exit", f"호가 반전 ({obi:.2f} < {self._exit_ob_max})", es, obi, vr
                )
            # 클라이맥스 소진: 거래량 폭증인데 고점을 못 넘음
            if vr > self._exit_vol_climax and self._prices:
                current_price = self._prices[-1]
                if current_price < self._session_high:
                    return OrderFlowSignal(
                        "exit",
                        f"클라이맥스 소진 (vol×{vr:.1f}, 현재가 {current_price} < 고점 {self._session_high})",
                        es, obi, vr,
                    )

            # --- 추매 조건 (모두 충족 시) ---
            if (
                unrealized_pnl >= self._pyramid_pnl_min
                and es >= self._pyramid_es_min
                and obi >= self._pyramid_ob_min
                and vr >= self._pyramid_vol_min
            ):
                return OrderFlowSignal(
                    "pyramid",
                    f"수급 추매 (ES={es:.0f}, OBI={obi:.2f}, vol×{vr:.1f}, pnl={unrealized_pnl:.2%})",
                    es, obi, vr,
                )

        return OrderFlowSignal("hold", "", es, obi, vr)


class OrderFlowBook:
    """여러 종목의 OrderFlowState를 관리하는 컨테이너."""

    __slots__ = ("_states", "_kwargs")

    def __init__(self, **state_kwargs: float | int) -> None:
        self._states: dict[str, OrderFlowState] = {}
        self._kwargs = state_kwargs

    def get_or_create(self, symbol: str) -> OrderFlowState:
        if symbol not in self._states:
            self._states[symbol] = OrderFlowState(**self._kwargs)
        return self._states[symbol]

    def remove(self, symbol: str) -> None:
        self._states.pop(symbol, None)

    def symbols(self) -> list[str]:
        return list(self._states)
