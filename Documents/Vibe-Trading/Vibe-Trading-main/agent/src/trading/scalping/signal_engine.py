"""SignalEngine — 점수 계산 + 눌림/재돌파 상태머신."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .constants import (
    MIN_ENTRY_SCORE, STRONG_ENTRY_SCORE,
    PULLBACK_MAX_WAIT_SECS,
    EXIT_EXEC_STRENGTH_MAX, EXIT_OB_IMBALANCE_MAX,
    W_EXEC_STRENGTH, W_VOL_RATIO, W_VWAP_GAP,
    W_OB_IMBALANCE, W_MARKET_STRENGTH, W_VOLATILITY,
    BREAKOUT_EXEC_MIN, BREAKOUT_CONFIRM_TICKS,
    MIN_VOL_RATIO, PULLBACK_MIN_PCT,
    LEADER_RANK_MAX, LEADER_MIN_SCORE,
    SHALLOW_PULLBACK_MIN_PCT, SHALLOW_PULLBACK_MAX_PCT,
    SHALLOW_ENTRY_SCORE, SHALLOW_ENTRY_EXEC_MIN,
    SHALLOW_ENTRY_VWAP_MIN_GAP, SHALLOW_ENTRY_OB_MIN,
    LEADER_HIGH_UPDATE_MIN_PCT,
)
from .events import TickEvent, SignalEvent
from .vwap import VWAPState, ATRState, PullbackTracker


@dataclass
class EntryScore:
    total: float
    exec_strength_score: float
    vol_ratio_score: float
    vwap_gap_score: float
    ob_imbalance_score: float
    market_strength_score: float
    volatility_score: float

    @property
    def is_strong(self) -> bool:
        return self.total >= STRONG_ENTRY_SCORE

    @property
    def is_valid(self) -> bool:
        return self.total >= MIN_ENTRY_SCORE


@dataclass
class SymbolState:
    """종목별 실시간 분석 상태."""
    symbol: str
    vwap: VWAPState = field(default_factory=VWAPState)
    atr: ATRState = field(default_factory=ATRState)
    pullback: PullbackTracker = field(default_factory=lambda: PullbackTracker(""))
    last_price: float = 0.0
    last_exec_strength: float = 0.0
    last_ob_imbalance: float = 1.0
    last_vol_ratio: float = 0.0     # 전일 동시간 대비 배율 (스캐너 주입)
    vi_detected_at: float = 0.0     # VI 발동 epoch
    morning_high: float = 0.0                          # 오전 관찰 고점 (스냅샷용)
    morning_exec_samples: list = field(default_factory=list)  # 오전 체결강도 샘플 (최대 200)
    last_tick_at: float = 0.0
    tick_count: int = 0
    leader_rank: int = 999
    leader_score: float = 0.0
    latest_scan_price: float = 0.0

    def __post_init__(self):
        self.pullback = PullbackTracker(self.symbol)


class SignalEngine:
    """
    역할:
    - 종목별 SymbolState 관리 (VWAP, ATR, 눌림 추적기)
    - 매 틱마다 체결강도·호가잔량비·VWAP 갭 계산
    - 점수 기반 진입 신호 생성
    - 눌림 → 재돌파 상태머신 관리

    실전 주의:
    - vol_ratio는 MarketScanner가 REST로 계산해서 주입 (틱에 없음)
    - ATR은 장 시작 전 bulk_load 후 분봉 완성마다 update_candle 호출
    - 점수 80 미만이면 "enter_watch", 90 이상이면 "enter_now"
    """

    def __init__(self) -> None:
        self._states: dict[str, SymbolState] = {}

    # ── Public getters (private _states 직접 접근 금지) ──────────────────────

    def get_symbol_state(self, symbol: str) -> Optional[SymbolState]:
        """종목 상태 조회. 미등록이면 None."""
        return self._states.get(symbol)

    def get_last_price(self, symbol: str) -> float:
        """BUG-25 FIX: 종목별 최신 체결가 반환 (미실현 PnL 계산용)."""
        st = self._states.get(symbol)
        return st.last_price if st else 0.0

    def get_exec_strength(self, symbol: str) -> float:
        st = self._states.get(symbol)
        return st.last_exec_strength if st else 100.0

    def get_exec_strength_samples(
        self,
        symbol: str,
        lookback_minutes: int = 30,
    ) -> list[float]:
        """최근 체결강도 샘플 반환.

        현재 저장소는 tick 기반 리스트이므로 timestamp가 없는 값은 최신 샘플로 간주한다.
        timestamp가 포함된 (ts, value) 형태도 테스트/향후 확장을 위해 지원한다.
        """
        st = self._states.get(symbol)
        if not st:
            return []
        cutoff = time.time() - lookback_minutes * 60
        values: list[float] = []
        for sample in st.morning_exec_samples:
            if isinstance(sample, tuple) and len(sample) >= 2:
                ts, value = sample[0], sample[1]
                if float(ts) >= cutoff:
                    values.append(float(value))
            else:
                values.append(float(sample))
        return values

    def get_ob_imbalance(self, symbol: str) -> float:
        st = self._states.get(symbol)
        return st.last_ob_imbalance if st else 1.0

    def get_vwap(self, symbol: str) -> float:
        st = self._states.get(symbol)
        return st.vwap.vwap if st else 0.0

    def get_atr(self, symbol: str) -> float:
        st = self._states.get(symbol)
        return st.atr.atr if st else 0.0

    def get_signal_snapshot(self, symbol: str) -> dict:
        """현재 신호 관련 수치 스냅샷 (TradeJournal 기록용)."""
        st = self._states.get(symbol)
        if not st:
            return {}
        return {
            "exec_strength": round(st.last_exec_strength, 1),
            "ob_imbalance": round(st.last_ob_imbalance, 3),
            "vwap": round(st.vwap.vwap, 0),
            "vwap_gap": round(st.vwap.gap(st.last_price), 4),
            "atr": round(st.atr.atr, 0),
            "vol_ratio": round(st.last_vol_ratio, 2),
            "pullback_phase": st.pullback.phase,
            "pullback_pct": round(st.pullback.pullback_pct, 4),
            "leader_rank": st.leader_rank,
            "leader_score": round(st.leader_score, 1),
            "tick_count": st.tick_count,
            "last_tick_age_sec": round(max(0.0, time.time() - st.last_tick_at), 1) if st.last_tick_at > 0 else None,
            "vwap_ready": st.vwap.vwap > 0,
            "atr_ready": st.atr.ready,
            "exec_strength_samples": len(st.morning_exec_samples),
        }

    def signal_summary(self, symbols: list[str] | set[str], score_threshold: float) -> dict:
        """운영 진단용: 후보/감시 종목이 왜 아직 진입하지 않았는지 집계한다."""
        counts = {
            "watchlist": len(symbols),
            "waiting_pullback": 0,
            "in_pullback": 0,
            "breakout_ready": 0,
            "score_below": 0,
            "exec_strength_below": 0,
            "vwap_not_ready": 0,
            "atr_missing": 0,
            "vol_ratio_missing": 0,
            "entry_signal": 0,
            "ticks_recent": 0,
            "near_entry": 0,
            "best_score": 0.0,
            "avg_score_gap": 0.0,
            "avg_exec_strength_gap": 0.0,
            "avg_vol_ratio_gap": 0.0,
            "avg_pullback_gap_pct": 0.0,
            "top_missing_metric": "none",
        }
        now = time.time()
        details: list[dict] = []
        score_gaps: list[float] = []
        exec_gaps: list[float] = []
        vol_gaps: list[float] = []
        pullback_gaps: list[float] = []
        for symbol in symbols:
            st = self._states.get(symbol)
            if not st:
                counts["waiting_pullback"] += 1
                details.append({
                    "symbol": symbol,
                    "phase": "UNREGISTERED",
                    "reject_reason": "not_registered",
                    "score": 0.0,
                    "score_gap": score_threshold,
                })
                score_gaps.append(float(score_threshold))
                continue
            if now - st.last_tick_at <= 30:
                counts["ticks_recent"] += 1
            effective_threshold = self._effective_score_threshold(st, score_threshold)
            reason = self._diagnose_reject_reason(st, effective_threshold)
            counts[reason] = counts.get(reason, 0) + 1
            gap = self._entry_gap_snapshot(st, effective_threshold)
            score_gaps.append(gap["score_gap"])
            exec_gaps.append(gap["exec_strength_gap"])
            vol_gaps.append(gap["vol_ratio_gap"])
            pullback_gaps.append(gap["pullback_gap_pct"])
            if gap["score"] > counts["best_score"]:
                counts["best_score"] = gap["score"]
            if gap["score_gap"] <= 5.0 and gap["exec_strength_gap"] <= 10.0:
                counts["near_entry"] += 1
            phase = st.pullback.phase.upper()
            details.append({
                "symbol": symbol,
                "phase": phase,
                "last_price": st.last_price,
                "registered_high": st.pullback.high,
                "pullback_pct": st.pullback.pullback_pct,
                "breakout_confirm_ticks": getattr(st.pullback, "_breakout_confirm_count", 0),
                "exec_strength": st.last_exec_strength,
                "vol_ratio": st.last_vol_ratio,
                "vwap_gap": st.vwap.gap(st.last_price),
                "ob_imbalance": st.last_ob_imbalance,
                "leader_rank": st.leader_rank,
                "leader_score": st.leader_score,
                "score_threshold": effective_threshold,
                "reject_reason": reason,
                **gap,
            })
        non_block_keys = {
            "watchlist", "ticks_recent", "near_entry", "best_score",
            "avg_score_gap", "avg_exec_strength_gap", "avg_vol_ratio_gap",
            "avg_pullback_gap_pct", "top_missing_metric",
        }
        block_counts = {k: v for k, v in counts.items() if k not in non_block_keys and v}
        top_block = max(block_counts.items(), key=lambda x: x[1])[0] if block_counts else "none"
        counts["top_block"] = top_block
        counts["avg_score_gap"] = round(sum(score_gaps) / len(score_gaps), 1) if score_gaps else 0.0
        counts["avg_exec_strength_gap"] = round(sum(exec_gaps) / len(exec_gaps), 1) if exec_gaps else 0.0
        counts["avg_vol_ratio_gap"] = round(sum(vol_gaps) / len(vol_gaps), 2) if vol_gaps else 0.0
        counts["avg_pullback_gap_pct"] = round(sum(pullback_gaps) / len(pullback_gaps), 2) if pullback_gaps else 0.0
        counts["top_missing_metric"] = self._top_missing_metric(counts)
        counts["details"] = sorted(details, key=lambda d: d.get("score_gap", 999.0))[:10]
        return counts

    # ── 외부 주입 ─────────────────────────────────────────────────────────────

    def register(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState(symbol)
        return self._states[symbol]

    def remove(self, symbol: str) -> None:
        self._states.pop(symbol, None)

    def inject_vol_ratio(self, symbol: str, vol_ratio: float) -> None:
        """MarketScanner에서 전일 동시간 대비 거래량 배율 주입."""
        st = self._states.get(symbol)
        if st:
            st.last_vol_ratio = vol_ratio

    def update_scan_context(
        self,
        symbol: str,
        *,
        price: float,
        vol_ratio: float,
        leader_rank: int = 999,
        leader_score: float = 0.0,
    ) -> None:
        """MarketScanner 값 최신화: 기존 watchlist도 거래량/리더/고점 갱신."""
        st = self.register(symbol)
        st.last_vol_ratio = vol_ratio
        st.leader_rank = leader_rank
        st.leader_score = leader_score
        st.latest_scan_price = price
        if price > 0:
            self.maybe_update_high(symbol, price)

    def inject_atr_candles(self, symbol: str, candles) -> None:
        """장 시작 전 과거 분봉 캔들 일괄 주입."""
        st = self.register(symbol)
        st.atr.bulk_load(candles)

    def update_atr_candle(self, symbol: str, high: float, low: float, close: float) -> None:
        """분봉 완성 시 ATR 갱신."""
        st = self._states.get(symbol)
        if st:
            st.atr.update_candle(high, low, close)

    def register_high(self, symbol: str, price: float) -> None:
        """고점 등록 — 눌림 추적 시작."""
        st = self._states.get(symbol)
        if st:
            st.pullback.register_high(price, time.time())

    def maybe_update_high(self, symbol: str, price: float) -> None:
        """watchlist 기준 고점을 실시간에 가깝게 갱신한다."""
        st = self._states.get(symbol)
        if not st or price <= 0:
            return
        if st.pullback.phase == "idle" or st.pullback.high <= 0:
            st.pullback.register_high(price, time.time())
            return
        if st.pullback.phase != "watching":
            return
        if price >= st.pullback.high * (1.0 + LEADER_HIGH_UPDATE_MIN_PCT):
            st.pullback.register_high(price, time.time())

    # ── 메인 틱 처리 ──────────────────────────────────────────────────────────

    def process_tick(self, tick: TickEvent, market_strength: float = 1.0) -> Optional[SignalEvent]:
        """
        매 틱 호출. 반환:
          None          — 신호 없음
          SignalEvent   — action: "enter_watch" | "enter_now" | "exit"
        """
        st = self._states.get(tick.symbol)
        if st is None:
            return None

        # VWAP 업데이트
        if tick.acml_vol > 0 and tick.acml_tr_pbmn > 0:
            st.vwap.update_acml(tick.acml_tr_pbmn, tick.acml_vol)
        else:
            st.vwap.update_tick(tick.price, tick.tick_vol)

        st.last_price = tick.price
        st.last_tick_at = time.time()
        st.tick_count += 1

        # 체결강도 계산
        total_vol = tick.buy_vol_total + tick.sell_vol_total
        if total_vol > 0:
            st.last_exec_strength = tick.buy_vol_total / total_vol * 100 * 2
            # KIS 체결강도 = (매수체결량/전체) × 100 × 2 → 100 기준 정규화
        else:
            st.last_exec_strength = 100.0

        # 오전 고점 및 체결강도 이력 추적 (점심 전략 백테스트용)
        if tick.price > st.morning_high:
            st.morning_high = tick.price
        st.morning_exec_samples.append(st.last_exec_strength)
        if len(st.morning_exec_samples) > 200:
            del st.morning_exec_samples[:-200]

        # 호가잔량비
        if tick.ask_qty > 0:
            st.last_ob_imbalance = tick.bid_qty / tick.ask_qty
        else:
            st.last_ob_imbalance = 1.0

        # VI 감지
        if tick.is_vi:
            st.vi_detected_at = time.time()
            return None

        # VI 쿨다운 / 해제 처리
        from .constants import VI_COOLDOWN_SECS
        if st.vi_detected_at > 0:
            if (time.time() - st.vi_detected_at) < VI_COOLDOWN_SECS:
                return None
            # VI 쿨다운 만료 → 눌림 추적기 리셋 + 현재가를 새 기준 고점으로 등록
            st.pullback.reset()
            st.pullback.register_high(tick.price, time.time())
            st.vi_detected_at = 0.0

        # 눌림/재돌파 상태 갱신
        pullback_phase = st.pullback.update(tick.price, time.time(), PULLBACK_MAX_WAIT_SECS)

        # 청산 신호 (보유 포지션 관련 — PositionManager에서 처리하지만 여기서도 감지)
        if self._is_exit_signal(st):
            return SignalEvent(
                symbol=tick.symbol,
                score=0.0,
                action="exit",
                reason=self._exit_reason(st),
                exec_strength=st.last_exec_strength,
                ob_imbalance=st.last_ob_imbalance,
                vwap_gap=st.vwap.gap(tick.price),
                atr=st.atr.atr,
                price=tick.price,
            )

        shallow_sig = self._shallow_pullback_signal(st, tick, market_strength)
        if shallow_sig:
            return shallow_sig

        # 진입 점수 계산 (breakout 확인 틱 + 체결강도 최소값 게이트)
        if pullback_phase == "breakout" and st.last_exec_strength >= BREAKOUT_EXEC_MIN:
            score = self._compute_score(st, tick, market_strength)
            action = "enter_now" if score.is_strong else ("enter_watch" if score.is_valid else None)
            if action:
                return SignalEvent(
                    symbol=tick.symbol,
                    score=score.total,
                    action=action,
                    reason=f"pullback_breakout score={score.total:.1f}",
                    exec_strength=st.last_exec_strength,
                    ob_imbalance=st.last_ob_imbalance,
                    vwap_gap=st.vwap.gap(tick.price),
                    atr=st.atr.atr,
                    price=tick.price,
                )

        return None

    def _shallow_pullback_signal(
        self,
        st: SymbolState,
        tick: TickEvent,
        market_strength: float,
    ) -> Optional[SignalEvent]:
        """대장주 전용 얕은 눌림 진입 경로."""
        if st.leader_rank > LEADER_RANK_MAX or st.leader_score < LEADER_MIN_SCORE:
            return None
        pb = st.pullback.pullback_pct
        if not (SHALLOW_PULLBACK_MIN_PCT <= pb <= SHALLOW_PULLBACK_MAX_PCT):
            return None
        if st.last_exec_strength < SHALLOW_ENTRY_EXEC_MIN:
            return None
        if st.last_ob_imbalance < SHALLOW_ENTRY_OB_MIN:
            return None
        vwap_gap = st.vwap.gap(tick.price)
        if vwap_gap < SHALLOW_ENTRY_VWAP_MIN_GAP:
            return None
        score = self._compute_score(st, tick, market_strength)
        if score.total < SHALLOW_ENTRY_SCORE:
            return None
        return SignalEvent(
            symbol=tick.symbol,
            score=score.total,
            action="enter_now",
            reason=(
                f"leader_shallow_pullback rank={st.leader_rank} "
                f"leader_score={st.leader_score:.1f} pullback={pb:.3f} score={score.total:.1f}"
            ),
            exec_strength=st.last_exec_strength,
            ob_imbalance=st.last_ob_imbalance,
            vwap_gap=vwap_gap,
            atr=st.atr.atr,
            price=tick.price,
        )

    def _diagnose_reject_reason(self, st: SymbolState, score_threshold: float) -> str:
        if st.last_tick_at <= 0:
            return "waiting_pullback"
        if st.last_vol_ratio <= 0:
            return "vol_ratio_missing"
        if st.leader_rank <= LEADER_RANK_MAX and st.leader_score >= LEADER_MIN_SCORE:
            pb = st.pullback.pullback_pct
            if pb < SHALLOW_PULLBACK_MIN_PCT:
                return "waiting_pullback"
            if pb <= SHALLOW_PULLBACK_MAX_PCT:
                if st.last_exec_strength < SHALLOW_ENTRY_EXEC_MIN:
                    return "exec_strength_below"
                if st.last_ob_imbalance < SHALLOW_ENTRY_OB_MIN:
                    return "spread_too_wide"
                score = self._compute_score(st, self._dummy_tick(st), 1.0)
                if score.total < score_threshold:
                    return "score_below"
                return "entry_signal"
        if not st.atr.ready:
            return "atr_missing"
        if not st.vwap.is_warmed_up:
            return "vwap_not_ready"
        if st.pullback.phase == "watching":
            return "waiting_pullback"
        if st.pullback.phase == "pullback":
            if st.last_exec_strength < BREAKOUT_EXEC_MIN:
                return "exec_strength_below"
            return "breakout_not_confirmed"
        if st.pullback.phase == "breakout":
            dummy = TickEvent(
                symbol=st.symbol,
                price=st.last_price,
                buy_vol_total=0,
                sell_vol_total=0,
                bid_qty=0,
                ask_qty=0,
                tick_vol=0,
                acml_vol=0,
                acml_tr_pbmn=0,
                time_str="",
            )
            score = self._compute_score(st, dummy, 1.0)
            if score.total < score_threshold:
                return "score_below"
            return "entry_signal"
        return "waiting_pullback"

    def _entry_gap_snapshot(self, st: SymbolState, score_threshold: float) -> dict:
        dummy = self._dummy_tick(st)
        score = self._compute_score(st, dummy, 1.0)
        breakout_ticks = int(getattr(st.pullback, "_breakout_confirm_count", 0) or 0)
        vwap_ticks = int(getattr(st.vwap, "_tick_count", 0) or 0)
        pullback_gap_pct = 0.0
        if st.pullback.phase == "watching":
            pullback_gap_pct = max(0.0, PULLBACK_MIN_PCT - st.pullback.pullback_pct) * 100
        return {
            "score": round(score.total, 1),
            "score_gap": round(max(0.0, score_threshold - score.total), 1),
            "exec_strength_gap": round(max(0.0, BREAKOUT_EXEC_MIN - st.last_exec_strength), 1),
            "vol_ratio_gap": round(max(0.0, MIN_VOL_RATIO - st.last_vol_ratio), 2),
            "pullback_gap_pct": round(pullback_gap_pct, 2),
            "breakout_ticks_missing": max(0, BREAKOUT_CONFIRM_TICKS - breakout_ticks) if st.pullback.phase == "pullback" else 0,
            "vwap_warmup_ticks_missing": max(0, 120 - vwap_ticks),
        }

    def _effective_score_threshold(self, st: SymbolState, default_threshold: float) -> float:
        if (
            st.leader_rank <= LEADER_RANK_MAX
            and st.leader_score >= LEADER_MIN_SCORE
            and st.pullback.pullback_pct <= SHALLOW_PULLBACK_MAX_PCT
        ):
            return min(float(default_threshold), SHALLOW_ENTRY_SCORE)
        return float(default_threshold)

    def _dummy_tick(self, st: SymbolState) -> TickEvent:
        return TickEvent(
            symbol=st.symbol,
            price=st.last_price,
            buy_vol_total=0,
            sell_vol_total=0,
            bid_qty=0,
            ask_qty=0,
            tick_vol=0,
            acml_vol=0,
            acml_tr_pbmn=0,
            time_str="",
        )

    def _top_missing_metric(self, counts: dict) -> str:
        weighted = {
            "score_gap": float(counts.get("avg_score_gap", 0.0)) / 10.0,
            "exec_strength_gap": float(counts.get("avg_exec_strength_gap", 0.0)) / 20.0,
            "vol_ratio_gap": float(counts.get("avg_vol_ratio_gap", 0.0)) / 1.0,
            "pullback_gap": float(counts.get("avg_pullback_gap_pct", 0.0)) / 1.0,
        }
        metric, value = max(weighted.items(), key=lambda item: item[1])
        return metric if value > 0 else "none"

    # ── 점수 계산 ─────────────────────────────────────────────────────────────

    def _compute_score(self, st: SymbolState, tick: TickEvent, market_strength: float) -> EntryScore:
        """
        가중치 합계 = 100:
          체결강도  30 — 핵심 수급 지표
          거래량배율 20 — 세력 참여 확인
          VWAP 갭   20 — 추세 방향 (VWAP 위여야 가점)
          호가imbal 15 — 즉각 수급
          시장강도  10 — 코스닥 지수 등 외부 환경
          변동성    5  — ATR 대비 현재 변동성 적정 여부
        """
        # 체결강도 (0~35): 150 이상 → 35점 선형
        es_score = min(st.last_exec_strength / 150.0, 1.0) * float(W_EXEC_STRENGTH)

        # 거래량 배율 (0~20): 3배 → 20점
        vol_score = min(st.last_vol_ratio / 3.0, 1.0) * float(W_VOL_RATIO)

        # VWAP 갭 (0~20): VWAP 위 +0.5% → 20점, 아래 → 0점 + 신뢰도 할인
        vwap_gap = st.vwap.gap(tick.price)
        vwap_weight = 0.5 if not st.vwap.is_warmed_up else 1.0
        if vwap_gap >= 0:
            vwap_score = min(vwap_gap / 0.005 * W_VWAP_GAP * vwap_weight, float(W_VWAP_GAP))
        else:
            vwap_score = 0.0

        # 호가잔량비 (0~10): 1.5 이상 → 10점
        ob_score = min(st.last_ob_imbalance / 1.5, 1.0) * float(W_OB_IMBALANCE)

        # 시장강도 (0~10): 0.0~1.0 범위 입력
        mkt_score = max(0.0, min(market_strength * W_MARKET_STRENGTH, float(W_MARKET_STRENGTH)))

        # 변동성 (0~5): ATR 준비 안 됐으면 중립 2.5점
        if st.atr.ready and tick.price > 0:
            atr_pct = st.atr.atr / tick.price
            # 0.5~2% ATR이 이상적 단타 변동성
            if 0.005 <= atr_pct <= 0.02:
                vol_v_score = float(W_VOLATILITY)
            elif atr_pct < 0.005:
                vol_v_score = W_VOLATILITY * (atr_pct / 0.005)
            else:
                vol_v_score = W_VOLATILITY * max(0.0, 1.0 - (atr_pct - 0.02) / 0.02)
        else:
            vol_v_score = W_VOLATILITY * 0.5

        total = es_score + vol_score + vwap_score + ob_score + mkt_score + vol_v_score

        return EntryScore(
            total=round(total, 1),
            exec_strength_score=round(es_score, 1),
            vol_ratio_score=round(vol_score, 1),
            vwap_gap_score=round(vwap_score, 1),
            ob_imbalance_score=round(ob_score, 1),
            market_strength_score=round(mkt_score, 1),
            volatility_score=round(vol_v_score, 1),
        )

    # ── 청산 신호 ─────────────────────────────────────────────────────────────

    def _is_exit_signal(self, st: SymbolState) -> bool:
        return (
            st.last_exec_strength < EXIT_EXEC_STRENGTH_MAX
            or st.last_ob_imbalance < EXIT_OB_IMBALANCE_MAX
        )

    def _exit_reason(self, st: SymbolState) -> str:
        reasons = []
        if st.last_exec_strength < EXIT_EXEC_STRENGTH_MAX:
            reasons.append(f"exec_strength={st.last_exec_strength:.0f}<{EXIT_EXEC_STRENGTH_MAX}")
        if st.last_ob_imbalance < EXIT_OB_IMBALANCE_MAX:
            reasons.append(f"ob_imbalance={st.last_ob_imbalance:.2f}<{EXIT_OB_IMBALANCE_MAX}")
        return ", ".join(reasons)
