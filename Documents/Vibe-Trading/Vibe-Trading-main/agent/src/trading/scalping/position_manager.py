"""PositionManager — 포지션 생성·갱신·청산 조건 판단."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Optional

from .constants import (
    ATR_STOP_MULTIPLIER, ATR_TRAIL_MULTIPLIER, TRAIL_STOP_MAX_PCT,
    MIN_STOP_PCT,
    PARTIAL_EXIT_1_PCT, PARTIAL_EXIT_1_RATIO,
    PARTIAL_EXIT_2_PCT, PARTIAL_EXIT_2_RATIO,
    FAST_EXIT_1_PCT, FAST_EXIT_1_RATIO, FAST_TIME_STOP_SECS,
    FAST_TIME_STOP_MIN_MFE, FAST_TRAIL_STOP_PCT,
    FORCE_CLOSE_TIME, SOFT_CLOSE_TIME,
    EXIT_EXEC_STRENGTH_MAX, EXIT_OB_IMBALANCE_MAX,
    COMMISSION_RATE, TAX_RATE_KOSDAQ,
    SNAPSHOT_VERSION,
)
from .events import FillEvent, OrderRequest, TickEvent
from .position_type import PositionType, from_value as _pt_from_value, intended_exit_for
from .venue import (
    ExecutionVenue,
    ListingMarket,
    MarketSession,
    VenuePolicy,
    enum_value,
    listing_market_from_legacy,
)

logger = logging.getLogger(__name__)


class PositionPhase(str, Enum):
    ENTERING  = "entering"    # 1차 진입 완료, 2차 진입 또는 full 대기
    FULL      = "full"        # 전량 진입 완료
    PARTIAL_1 = "partial_1"   # 1차 익절 완료, break-even stop 활성
    PARTIAL_2 = "partial_2"   # 2차 익절 완료, trailing only
    CLOSED    = "closed"


@dataclass
class Position:
    symbol: str
    entry_price: float         # 1차 진입가
    avg_price: float           # 평균 단가 (추가 진입 시 갱신)
    total_qty: int             # 최초 진입 수량
    remaining_qty: int         # 잔여 수량
    phase: PositionPhase
    atr_at_entry: float        # 진입 시 ATR (손절 기준 고정)

    # ── 손절 / 트레일링 ───────────────────────────────────────────────────────
    hard_stop: float           # entry - ATR × 1.2  (변하지 않음)
    break_even_stop: float     # 1차 익절 체결 후 avg_price로 이동
    trailing_high: float       # 진입 이후 최고가
    trailing_stop: float       # max(ATR×1.0, high×(1-1.8%))

    opened_at: datetime = field(default_factory=datetime.now)
    realized_pnl: float = 0.0
    commission_paid: float = 0.0

    # ── 쿨다운 / 중복 방지 ───────────────────────────────────────────────────
    exit_1_triggered: bool = False
    exit_2_triggered: bool = False

    # ── 시장 구분 ────────────────────────────────────────────────────────────
    market: str = "KOSDAQ"   # "KOSDAQ" | "KOSPI" — 세금/tick size 계산용

    # ── 포지션 목적 분류 (전략 간 충돌 방지 필수) ─────────────────────────────
    position_type: PositionType = field(default=PositionType.INTRADAY_SCALP)
    strategy_id: str = ""                       # "intraday_scalp" | "lunch_rebound" | "close_bet"
    entry_session: str = "morning"              # "morning"|"lunch"|"close_auction"|"after_market"|"broker_recovered"
    intended_exit_session: str = "same_day"     # "same_day" | "next_open" | "manual"
    listing_market: ListingMarket = ListingMarket.KOSDAQ
    execution_venue: ExecutionVenue = ExecutionVenue.KRX
    preferred_venue: ExecutionVenue = ExecutionVenue.KRX
    actual_venue: ExecutionVenue = ExecutionVenue.UNKNOWN
    venue_policy: VenuePolicy = VenuePolicy.KRX_ONLY
    market_session: MarketSession = MarketSession.KRX_REGULAR
    krx_entry_price: float = 0.0
    nxt_reference_price: float = 0.0
    venue_price_gap_at_entry: float = 0.0
    nxt_after_signal: str = ""
    nxt_pre_signal: str = ""

    @classmethod
    def from_snapshot(cls, data: dict) -> "Position":
        """StateStore 스냅샷에서 Position 복구.
        BUG-10/11/12/13 FIX: phase, exit_flags, realized_pnl, total_qty 모두 복원.
        POSITION_TYPE FIX: opened_at, position_type, strategy_id 복원.
        """
        phase_str = data.get("phase") or PositionPhase.ENTERING.value
        try:
            phase = PositionPhase(phase_str)
        except ValueError:
            phase = PositionPhase.ENTERING

        avg_price = float(data.get("avg_price") or 0)
        remaining_qty = int(data.get("remaining_qty") or 0)
        total_qty = int(data.get("total_qty") or remaining_qty)

        # opened_at: 저장된 ISO 문자열 복원. 없으면 경고 로그 후 sentinel 값 사용.
        opened_at_raw = data.get("opened_at")
        if opened_at_raw:
            try:
                opened_at = datetime.fromisoformat(opened_at_raw)
            except (ValueError, TypeError):
                logger.warning(
                    "Position %s: opened_at '%s' parse failed — using epoch sentinel",
                    data.get("symbol"), opened_at_raw,
                )
                opened_at = datetime(2000, 1, 1)
        else:
            logger.warning(
                "Position %s: opened_at missing from snapshot — using epoch sentinel",
                data.get("symbol"),
            )
            opened_at = datetime(2000, 1, 1)

        # position_type: 없으면 UNKNOWN으로 경고
        pt_raw = data.get("position_type")
        position_type = _pt_from_value(pt_raw)
        if not pt_raw:
            logger.warning(
                "Position %s: position_type missing from snapshot — defaulting to UNKNOWN",
                data.get("symbol"),
            )

        pos = cls(
            symbol=data["symbol"],
            entry_price=float(data.get("entry_price") or avg_price),
            avg_price=avg_price,
            total_qty=total_qty,
            remaining_qty=remaining_qty,
            phase=phase,
            atr_at_entry=float(data.get("atr_at_entry") or 0),
            hard_stop=float(data.get("hard_stop") or 0),
            break_even_stop=float(data.get("break_even_stop") or 0),
            trailing_high=float(data.get("trailing_high") or avg_price),
            trailing_stop=float(data.get("trailing_stop") or 0),
            realized_pnl=float(data.get("realized_pnl") or 0),
            market=data.get("market") or "KOSDAQ",
            opened_at=opened_at,
            position_type=position_type,
            strategy_id=data.get("strategy_id") or position_type.value,
            entry_session=data.get("entry_session") or "broker_recovered",
            intended_exit_session=data.get("intended_exit_session") or intended_exit_for(position_type),
            listing_market=cls._enum_or_default(ListingMarket, data.get("listing_market"), listing_market_from_legacy(data.get("market"))),
            execution_venue=cls._enum_or_default(ExecutionVenue, data.get("execution_venue"), ExecutionVenue.KRX),
            preferred_venue=cls._enum_or_default(ExecutionVenue, data.get("preferred_venue"), ExecutionVenue.KRX),
            actual_venue=cls._enum_or_default(ExecutionVenue, data.get("actual_venue"), ExecutionVenue.UNKNOWN),
            venue_policy=cls._enum_or_default(VenuePolicy, data.get("venue_policy"), VenuePolicy.KRX_ONLY),
            market_session=cls._enum_or_default(MarketSession, data.get("market_session"), MarketSession.KRX_REGULAR),
            krx_entry_price=float(data.get("krx_entry_price") or avg_price),
            nxt_reference_price=float(data.get("nxt_reference_price") or 0),
            venue_price_gap_at_entry=float(data.get("venue_price_gap_at_entry") or 0),
            nxt_after_signal=str(data.get("nxt_after_signal") or ""),
            nxt_pre_signal=str(data.get("nxt_pre_signal") or ""),
        )
        pos.exit_1_triggered = bool(data.get("exit_1_triggered") or False)
        pos.exit_2_triggered = bool(data.get("exit_2_triggered") or False)
        return pos

    @staticmethod
    def _enum_or_default(enum_cls, raw, default):
        if isinstance(raw, enum_cls):
            return raw
        try:
            return enum_cls(raw)
        except Exception:
            return default


class PositionManager:
    """
    역할:
    - FillEvent 수신 시 Position 생성/업데이트
    - 매 틱마다 check_exits() 호출 → OrderRequest 반환 (청산 주문)
    - 청산 우선순위:
        1. 강제 청산 시간 (15:20)
        2. 소프트 청산 시간 (15:10 + 조건 미달)
        3. Hard stop loss
        4. VWAP 이탈
        5. 체결강도 급락
        6. 호가 imbalance 반전
        7. 트레일링 스탑
        8. 2차 익절
        9. 1차 익절

    실전 주의:
    - 체결 이벤트 수신 후 break_even_stop 이동 (on_fill_exit_tp1 호출)
    - 손절가는 호가단위(틱 사이즈)로 rounding 필수 (KIS는 이미 broker가 처리)
    - 갭하락 시 hard_stop 아래서 체결 → net_pnl 계산 시 실제 체결가 사용
    """

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    # ── 포지션 생성 ───────────────────────────────────────────────────────────

    def on_fill_entry(
        self,
        fill: FillEvent,
        atr: float,
        *,
        position_type: PositionType = PositionType.INTRADAY_SCALP,
        strategy_id: str = "",
        entry_session: str = "morning",
        intended_exit_session: str = "same_day",
        listing_market: ListingMarket = ListingMarket.KOSDAQ,
        preferred_venue: ExecutionVenue = ExecutionVenue.KRX,
        actual_venue: ExecutionVenue = ExecutionVenue.KRX,
        venue_policy: VenuePolicy = VenuePolicy.KRX_ONLY,
        market_session: MarketSession = MarketSession.KRX_REGULAR,
        krx_entry_price: float = 0.0,
        nxt_reference_price: float = 0.0,
        venue_price_gap_at_entry: float = 0.0,
        nxt_after_signal: str = "",
        nxt_pre_signal: str = "",
    ) -> Position:
        """매수 체결 이벤트 → 신규 포지션 생성."""
        symbol = fill.symbol

        if symbol in self._positions and self._positions[symbol].phase != PositionPhase.CLOSED:
            # 추가 진입 (2차 매수): avg_price 재계산
            pos = self._positions[symbol]
            prev_cost = pos.avg_price * (pos.total_qty - pos.remaining_qty)
            new_cost   = fill.fill_price * fill.filled_qty
            new_total  = pos.total_qty  + fill.filled_qty
            pos.avg_price    = (prev_cost + new_cost) / new_total if new_total else pos.avg_price
            pos.total_qty    = new_total
            pos.remaining_qty += fill.filled_qty
            pos.commission_paid += fill.commission
            pos.phase = PositionPhase.FULL
            pos.actual_venue = actual_venue
            pos.preferred_venue = preferred_venue
            pos.venue_policy = venue_policy
            pos.market_session = market_session
            logger.info("Position add: %s avg=%.0f qty=%d", symbol, pos.avg_price, new_total)
            return pos

        # 신규 포지션
        hard_stop = self._calc_hard_stop(fill.fill_price, atr)
        pos = Position(
            symbol=symbol,
            entry_price=fill.fill_price,
            avg_price=fill.fill_price,
            total_qty=fill.filled_qty,
            remaining_qty=fill.filled_qty,
            phase=PositionPhase.ENTERING,
            atr_at_entry=atr,
            hard_stop=hard_stop,
            break_even_stop=0.0,
            trailing_high=fill.fill_price,
            trailing_stop=self._calc_trailing_stop(fill.fill_price, fill.fill_price, atr),
            commission_paid=fill.commission,
            position_type=position_type,
            strategy_id=strategy_id or position_type.value,
            entry_session=entry_session,
            intended_exit_session=intended_exit_session,
            listing_market=listing_market,
            execution_venue=actual_venue,
            preferred_venue=preferred_venue,
            actual_venue=actual_venue,
            venue_policy=venue_policy,
            market_session=market_session,
            krx_entry_price=krx_entry_price or fill.fill_price,
            nxt_reference_price=nxt_reference_price,
            venue_price_gap_at_entry=venue_price_gap_at_entry,
            nxt_after_signal=nxt_after_signal,
            nxt_pre_signal=nxt_pre_signal,
        )
        self._positions[symbol] = pos
        logger.info(
            "Position open: %s entry=%.0f qty=%d hard_stop=%.0f type=%s",
            symbol, fill.fill_price, fill.filled_qty, hard_stop, position_type.value,
        )
        return pos

    def on_fill_exit(self, fill: FillEvent) -> Optional[Position]:
        """매도 체결 이벤트 → 포지션 수량 차감."""
        pos = self._positions.get(fill.symbol)
        if not pos:
            return None

        pos.remaining_qty -= fill.filled_qty
        pnl = (fill.fill_price - pos.avg_price) * fill.filled_qty
        pos.realized_pnl += pnl - fill.commission - fill.tax
        pos.commission_paid += fill.commission

        # 1차 익절 체결 직후 break-even stop 활성화
        if fill.reason == "exit_tp1":
            pos.break_even_stop = pos.avg_price
            pos.phase = PositionPhase.PARTIAL_1
            logger.info("Break-even stop set: %s at %.0f", fill.symbol, pos.break_even_stop)

        elif fill.reason == "exit_tp2":
            pos.phase = PositionPhase.PARTIAL_2

        if pos.remaining_qty <= 0:
            pos.phase = PositionPhase.CLOSED
            logger.info(
                "Position closed: %s realized_pnl=%.0f",
                fill.symbol, pos.realized_pnl,
            )

        return pos

    # ── 청산 조건 체크 (매 틱) ───────────────────────────────────────────────

    def check_exits(
        self,
        symbol: str,
        tick: TickEvent,
        exec_strength: float,
        ob_imbalance: float,
        vwap: float,
        now_time: time,
    ) -> Optional[OrderRequest]:
        """청산 조건 우선순위대로 체크. 조건 충족 시 OrderRequest 반환."""
        pos = self._positions.get(symbol)
        if not pos or pos.phase == PositionPhase.CLOSED or pos.remaining_qty <= 0:
            return None

        price = tick.price
        self._update_trailing(pos, price)

        # ── CLOSE_BET: 장중 시간 게이트 전체 스킵 — 익일 청산 엔진이 담당 ────────
        if pos.position_type == PositionType.CLOSE_BET:
            # Hard stop만 적용 (갭다운/급락 긴급 보호)
            if price <= pos.hard_stop:
                return self._sell_all_market(pos, reason="exit_sl")
            return None

        # ── UNKNOWN: 보수적 — hard stop + FORCE_CLOSE_TIME만 적용 ───────────────
        if pos.position_type == PositionType.UNKNOWN:
            if now_time >= FORCE_CLOSE_TIME:
                logger.warning("UNKNOWN position force-close: %s", pos.symbol)
                return self._sell_all(pos, price, reason="exit_time_force_unknown")
            if price <= pos.hard_stop:
                return self._sell_all_market(pos, reason="exit_sl")
            return None

        # ── INTRADAY_SCALP / LUNCH_REBOUND: 기존 전체 청산 로직 ─────────────────

        # 1. 강제 청산 시간
        if now_time >= FORCE_CLOSE_TIME:
            return self._sell_all(pos, price, reason="exit_time_force")

        # 2. 소프트 청산 시간 (조건 미달이면 청산)
        if now_time >= SOFT_CLOSE_TIME:
            if exec_strength < 100 or ob_imbalance < 1.0:
                return self._sell_all(pos, price, reason="exit_time_soft")

        # 3. Hard stop loss → 즉시 시장가 (BUG-32 FIX: 갭하락 시 limit 지연 방지)
        if price <= pos.hard_stop:
            return self._sell_all_market(pos, reason="exit_sl")

        fast_scalp = pos.strategy_id in {
            "opening_momentum",
            "shallow_pullback",
            "leader_only_shallow_pullback",
            "momentum_continuation",
        }
        pnl_pct = (price - pos.avg_price) / pos.avg_price if pos.avg_price > 0 else 0.0
        mfe_pct = (pos.trailing_high - pos.avg_price) / pos.avg_price if pos.avg_price > 0 else 0.0
        holding_sec = (datetime.now() - pos.opened_at).total_seconds()
        if fast_scalp and holding_sec >= FAST_TIME_STOP_SECS and mfe_pct < FAST_TIME_STOP_MIN_MFE:
            return self._sell_all(pos, price, reason="exit_time_no_mfe")

        # 4. Break-even stop → 즉시 시장가 (BUG-32 FIX)
        if pos.break_even_stop > 0 and price <= pos.break_even_stop:
            return self._sell_all_market(pos, reason="exit_be_stop")

        # 5. VWAP 이탈 (VWAP 아래 + 체결강도 약세)
        if vwap > 0 and price < vwap * 0.998 and exec_strength < 95:
            return self._sell_all(pos, price, reason="exit_vwap_break")

        # 6. 체결강도 급락
        if exec_strength < EXIT_EXEC_STRENGTH_MAX:
            return self._sell_all(pos, price, reason=f"exit_exec_weak:{exec_strength:.0f}")

        # 7. 호가 imbalance 반전
        if ob_imbalance < EXIT_OB_IMBALANCE_MAX:
            return self._sell_all(pos, price, reason=f"exit_ob_weak:{ob_imbalance:.2f}")

        # 8. 트레일링 스탑 (PARTIAL_1 이후 또는 FULL)
        if pos.phase in (PositionPhase.FULL, PositionPhase.PARTIAL_1, PositionPhase.PARTIAL_2):
            if price <= pos.trailing_stop:
                return self._sell_all(pos, price, reason="exit_trail")
        if fast_scalp and pos.trailing_high > 0 and price <= pos.trailing_high * (1.0 - FAST_TRAIL_STOP_PCT):
            return self._sell_all(pos, price, reason="exit_fast_trail")

        # 9. 2차 익절
        if not pos.exit_2_triggered and pos.phase == PositionPhase.PARTIAL_1:
            pnl_pct = (price - pos.avg_price) / pos.avg_price
            if pnl_pct >= PARTIAL_EXIT_2_PCT:
                pos.exit_2_triggered = True
                # BUG-31 FIX: 소량 포지션에서 qty=0이 되지 않도록 최소 1주 보장
                qty = max(1, round(pos.total_qty * PARTIAL_EXIT_2_RATIO))
                qty = min(qty, pos.remaining_qty)  # 잔여 수량 초과 방지
                if qty > 0:
                    return OrderRequest(
                        symbol=symbol, side="sell", qty=qty,
                        price=price, order_type="limit",
                        reason="exit_tp2", ref_id=symbol,
                        market=pos.market,
                        position_type=pos.position_type,
                        listing_market=pos.listing_market,
                        execution_venue=pos.execution_venue,
                        preferred_venue=pos.preferred_venue,
                        actual_venue=pos.actual_venue,
                        venue_policy=pos.venue_policy,
                        market_session=pos.market_session,
                    )

        # 10. 1차 익절
        if not pos.exit_1_triggered and pos.phase in (PositionPhase.ENTERING, PositionPhase.FULL):
            first_exit_pct = FAST_EXIT_1_PCT if fast_scalp else PARTIAL_EXIT_1_PCT
            first_exit_ratio = FAST_EXIT_1_RATIO if fast_scalp else PARTIAL_EXIT_1_RATIO
            if pnl_pct >= first_exit_pct:
                pos.exit_1_triggered = True
                # BUG-31 FIX: 최소 1주 보장
                qty = max(1, round(pos.total_qty * first_exit_ratio))
                qty = min(qty, pos.remaining_qty)
                if qty > 0:
                    return OrderRequest(
                        symbol=symbol, side="sell", qty=qty,
                        price=price, order_type="limit",
                        reason="exit_tp1", ref_id=symbol,
                        market=pos.market,
                        position_type=pos.position_type,
                        listing_market=pos.listing_market,
                        execution_venue=pos.execution_venue,
                        preferred_venue=pos.preferred_venue,
                        actual_venue=pos.actual_venue,
                        venue_policy=pos.venue_policy,
                        market_session=pos.market_session,
                    )

        return None

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    def restore_position(self, data: dict) -> Position:
        """StateStore 스냅샷에서 Position 직접 등록 (BUG-10/11/12/13 FIX).
        from_snapshot()으로 모든 필드 복원 후 _positions에 바로 삽입.
        """
        pos = Position.from_snapshot(data)
        self._positions[pos.symbol] = pos
        logger.info(
            "Position restored: %s phase=%s qty=%d avg=%.0f exit1=%s exit2=%s",
            pos.symbol, pos.phase.value, pos.remaining_qty, pos.avg_price,
            pos.exit_1_triggered, pos.exit_2_triggered,
        )
        return pos

    def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def active_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if p.phase != PositionPhase.CLOSED}

    def unrealized_pnl(self, symbol: str, current_price: float) -> float:
        pos = self._positions.get(symbol)
        if not pos or pos.phase == PositionPhase.CLOSED:
            return 0.0
        return (current_price - pos.avg_price) * pos.remaining_qty

    def _sell_all(self, pos: Position, price: float, reason: str) -> OrderRequest:
        return OrderRequest(
            symbol=pos.symbol,
            side="sell",
            qty=pos.remaining_qty,
            price=price,
            order_type="limit",
            reason=reason,
            ref_id=pos.symbol,
            market=pos.market,
            position_type=pos.position_type,
            listing_market=pos.listing_market,
            execution_venue=pos.execution_venue,
            preferred_venue=pos.preferred_venue,
            actual_venue=pos.actual_venue,
            venue_policy=pos.venue_policy,
            market_session=pos.market_session,
        )

    def _sell_all_market(self, pos: Position, reason: str) -> OrderRequest:
        """BUG-32 FIX: 손절/break-even은 즉시 시장가 청산 (갭하락 시 limit 지연 방지)."""
        return OrderRequest(
            symbol=pos.symbol,
            side="sell",
            qty=pos.remaining_qty,
            price=0,
            order_type="market",
            reason=reason,
            ref_id=pos.symbol,
            market=pos.market,
            position_type=pos.position_type,
            listing_market=pos.listing_market,
            execution_venue=pos.execution_venue,
            preferred_venue=pos.preferred_venue,
            actual_venue=pos.actual_venue,
            venue_policy=pos.venue_policy,
            market_session=pos.market_session,
        )

    def _calc_hard_stop(self, entry: float, atr: float) -> float:
        min_stop = entry * (1.0 - MIN_STOP_PCT)
        atr_stop = entry - atr * ATR_STOP_MULTIPLIER
        # min_stop은 이격 거리 하한선 — ATR이 더 크면 ATR 사용, 작으면 하한선으로 강제
        return min(atr_stop, min_stop)

    def _calc_trailing_stop(self, high: float, entry: float, atr: float) -> float:
        atr_trail = high - atr * ATR_TRAIL_MULTIPLIER
        pct_trail = high * (1.0 - TRAIL_STOP_MAX_PCT)
        return max(atr_trail, pct_trail, entry * (1.0 - MIN_STOP_PCT))

    def _update_trailing(self, pos: Position, price: float) -> None:
        if price > pos.trailing_high:
            pos.trailing_high = price
            new_stop = self._calc_trailing_stop(
                pos.trailing_high, pos.avg_price, pos.atr_at_entry,
            )
            # 트레일링 스탑은 단조 증가만 허용 (갱신 후 후퇴 방지)
            pos.trailing_stop = max(pos.trailing_stop, new_stop)
