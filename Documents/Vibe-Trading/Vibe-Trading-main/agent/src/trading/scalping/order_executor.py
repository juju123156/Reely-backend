"""OrderExecutor — 주문 상태머신 + 미체결/부분체결 처리."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .constants import (
    ORDER_RETRY_MAX, ORDER_RETRY_DELAY_SEC,
    ORDER_FILL_TIMEOUT_SEC, MAX_SLIPPAGE_PCT,
    COMMISSION_RATE, TAX_RATE_KOSDAQ, TAX_RATE_KOSPI,
    NO_ORDER_AFTER, AFTER_MARKET_FILL_TIMEOUT,
)
from .events import FillEvent, OrderRequest
from .kr_market_utils import round_to_tick
from .order_simulator import OrderFillSimulator
from .position_type import PositionType
from .venue import ExecutionVenue, VenuePolicy

logger = logging.getLogger(__name__)

# ── 1. 주문 상태 머신 ─────────────────────────────────────────────────────────

class OrderStatus(Enum):
    PENDING          = "pending"           # 제출 전
    SUBMITTED        = "submitted"         # KIS에 전달됨
    PARTIALLY_FILLED = "partially_filled"  # 부분 체결
    FILLED           = "filled"            # 전량 체결
    CANCELED         = "canceled"          # 취소됨
    REJECTED         = "rejected"          # KIS 거부 (VI, 권한 등)
    TIMED_OUT        = "timed_out"         # 체결 타임아웃
    UNKNOWN          = "unknown"           # 상태 불명 (reconcile 전)


@dataclass
class OrderRecord:
    """주문 1건의 전체 생명주기."""
    req: OrderRequest
    order_no: str = ""
    krx_org_no: str = ""
    status: OrderStatus = OrderStatus.PENDING
    record_id: str = ""               # pipeline_event record_id 연결 (req.ref_id에서 복사)
    expected_price: float = 0.0      # 제출 시 기대 체결가
    filled_qty: int = 0              # 누적 체결 수량
    remaining_qty: int = 0           # 미체결 잔량
    avg_fill_price: float = 0.0      # 누적 평균 체결가
    slippage_pct: float = 0.0        # (avg_fill - expected) / expected
    submitted_at: float = field(default_factory=time.monotonic)
    filled_at: float = 0.0
    error_msg: str = ""
    replace_count: int = 0
    cancel_reason: str = ""
    replace_reason: str = ""
    reject_reason: str = ""          # REJECTED 상세 원인

    @property
    def order_age_ms(self) -> int:
        return int(max(0.0, time.monotonic() - self.submitted_at) * 1000)

    def apply_partial_fill(self, qty: int, price: float) -> None:
        """부분체결 1건 반영 — 평균단가 재계산."""
        prev_cost = self.avg_fill_price * self.filled_qty
        new_cost   = price * qty
        self.filled_qty    += qty
        self.remaining_qty  = max(0, self.req.qty - self.filled_qty)
        self.avg_fill_price = (prev_cost + new_cost) / self.filled_qty if self.filled_qty else 0.0
        if self.remaining_qty == 0:
            self.status    = OrderStatus.FILLED
            self.filled_at = time.monotonic()
            if self.expected_price > 0:
                diff = (self.avg_fill_price - self.expected_price) / self.expected_price
                if self.req.side == "sell":
                    diff = -diff
                self.slippage_pct = diff
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def to_fill_event(self) -> FillEvent:
        commission = self.avg_fill_price * self.filled_qty * COMMISSION_RATE
        tax_rate = TAX_RATE_KOSPI if self.req.market == "KOSPI" else TAX_RATE_KOSDAQ
        tax = self.avg_fill_price * self.filled_qty * tax_rate if self.req.side == "sell" else 0.0
        return FillEvent(
            order_no=self.order_no,
            symbol=self.req.symbol,
            side=self.req.side,
            filled_qty=self.filled_qty,
            fill_price=self.avg_fill_price,
            commission=commission,
            tax=tax,
            reason=self.req.reason,
            listing_market=self.req.listing_market,
            execution_venue=self.req.execution_venue,
            preferred_venue=self.req.preferred_venue,
            actual_venue=self.req.actual_venue,
            venue_policy=self.req.venue_policy,
            market_session=self.req.market_session,
        )


# ── 2. 미체결 타임아웃 설정 ───────────────────────────────────────────────────

ENTRY_FILL_TIMEOUT = 5.0    # 진입 주문: 5초 이상 미체결 → 취소
EXIT_FILL_TIMEOUT  = 3.0    # 청산 주문: 3초 이상 미체결 → 시장가 전환
_EXIT_REASONS = {"exit_sl", "exit_trail", "exit_tp1", "exit_tp2",
                 "exit_time_force", "exit_time_soft", "kill_switch",
                 "exit_be_stop", "exit_vwap_break",
                 "exit_exec_weak", "exit_ob_weak"}


class OrderExecutor:
    """
    역할:
    - OrderRequest → KIS place_order_cash() 호출
    - OrderRecord로 상태 머신 관리 (PENDING → SUBMITTED → FILLED/CANCELED/REJECTED)
    - 미체결 타임아웃: 진입 5초, 청산 3초 → 시장가 전환
    - 부분체결: apply_partial_fill()로 avg_price 누적 재계산
    - 슬리피지: expected_price vs avg_fill_price 저장
    - on_fill_notify(): H0STCNI9 WebSocket 체결통보 수신 연결점

    실전 주의:
    - dry_run=True 이면 즉시 가상 체결 반환
    - VI 오류 수신 시 재시도 없이 REJECTED 처리
    - "submit 성공 ≠ 체결 성공": 반드시 wait_fill() 로 체결 확인
    """

    def __init__(
        self,
        adapter: Any,
        env: str = "demo",
        dry_run: bool = True,
        dry_run_order: bool = False,
        on_error: Optional[Callable[[str, Exception], None]] = None,
    ) -> None:
        self._adapter = adapter
        self._env = env
        self._dry_run = dry_run
        self._dry_run_order = dry_run_order
        self._on_error = on_error                         # 오류 시 Kill Switch 트리거용
        self._simulator = OrderFillSimulator()
        self._market_snapshots: dict[str, Any] = {}

        self._records: dict[str, OrderRecord] = {}        # order_no → OrderRecord
        self._fill_futures: dict[str, asyncio.Future] = {} # order_no → Future (H0STCNI9 연결)
        self._pre_sell_qty: dict[str, int] = {}            # order_no → pre-sell qty (REST fallback용)

        # 연속 API 오류 카운터 → Kill Switch 트리거 기준
        self._consecutive_errors: int = 0
        self._MAX_CONSECUTIVE_ERRORS = 3

    # ── 주문 제출 ─────────────────────────────────────────────────────────────

    async def submit(
        self,
        req: OrderRequest,
        emergency: bool = False,
        force_simulate: bool = False,
    ) -> Optional[str]:
        """주문 제출. 성공 시 order_no 반환, 실패 시 None.

        emergency=True: NO_ORDER_AFTER 이후에도 청산 주문 허용 (kill_switch/STOPPING 시).
        force_simulate=True: dry_run_live 모드 — API 차단, FakeBroker 즉시 체결 시뮬.
        """
        effective_dry_run = self._dry_run or force_simulate
        if force_simulate and not self._dry_run:
            order_no = f"DRL{int(time.time() * 1000) % 100000:05d}"
            record = OrderRecord(
                req=req,
                expected_price=req.price,
                remaining_qty=req.qty,
                record_id=req.ref_id or "",
            )
            record.order_no = order_no
            record.status = OrderStatus.SUBMITTED
            self._records[order_no] = record
            logger.info(
                "DRY_RUN_LIVE simulated submit: %s %s %s qty=%d price=%.0f no=%s",
                req.symbol, req.side, req.reason, req.qty, req.price, order_no,
            )
            loop = asyncio.get_event_loop()
            sim_price = req.price if req.price > 0 else float(
                self._market_snapshots.get(req.symbol, {}).get("close", 10_000)
            )
            fill_fut: asyncio.Future = loop.create_future()
            self._fill_futures[order_no] = fill_fut
            # 즉시 전량 체결 시뮬 (FakeBroker — dry_run_live 전용)
            record.avg_fill_price = sim_price
            record.filled_qty = req.qty
            record.remaining_qty = 0
            record.status = OrderStatus.FILLED
            if not fill_fut.done():
                fill_fut.set_result(record)
            return order_no

        # 15:19:30 이후 실전 주문 금지 — 동시호가 주문 혼입 방지
        # emergency=True 이면 청산/비상 목적으로 한시적 허용 (단, buy는 항상 차단)
        if not effective_dry_run and datetime.now().time() >= NO_ORDER_AFTER:
            if emergency and req.side == "sell":
                logger.warning(
                    "Emergency sell after NO_ORDER_AFTER (%s): %s %s",
                    NO_ORDER_AFTER, req.symbol, req.reason,
                )
            else:
                logger.warning(
                    "Order blocked after NO_ORDER_AFTER (%s): %s %s", NO_ORDER_AFTER, req.symbol, req.reason,
                )
                return None

        if (
            req.ord_dvsn_override == "07"
            and self._env == "demo"
            and not self._dry_run
        ):
            logger.error("After-market single-price order blocked in VTS/demo: %s", req.symbol)
            return None

        excg_id = self._excg_id_for_request(req)
        if excg_id == "NXT" and self._env == "demo" and not self._dry_run:
            logger.error(
                "Direct NXT order blocked in VTS/demo: %s venue_policy=%s preferred=%s",
                req.symbol, req.venue_policy.value, req.preferred_venue.value,
            )
            return None

        # 지정가 주문은 KRX 호가단위로 보정 — 미준수 시 KIS REJECTED
        # BUG-28 FIX: buy는 "up" (체결 가능한 호가), sell은 "down" (체결 우선)
        if req.order_type == "limit" and req.price > 0:
            mode = "up" if req.side == "buy" else "down"
            rounded = round_to_tick(req.price, req.market, mode)
            if rounded != int(req.price):
                logger.debug(
                    "Tick-size adjusted: %s %.0f→%d (%s)", req.symbol, req.price, rounded, req.market,
                )
                req = dataclasses.replace(req, price=float(rounded))

        record = OrderRecord(
            req=req,
            expected_price=req.price,
            remaining_qty=req.qty,
            record_id=req.ref_id or "",
        )
        loop = asyncio.get_event_loop()

        if self._dry_run_order and not self._dry_run:
            order_no = f"SIM{int(time.time() * 1000) % 100000:05d}"
            record.order_no = order_no
            record.status = OrderStatus.SUBMITTED
            self._records[order_no] = record
            logger.info(
                "DRY_RUN_ORDER blocked before API: %s %s %s qty=%d price=%.0f no=%s",
                req.symbol, req.side, req.reason, req.qty, req.price, order_no,
            )
            return order_no

        for attempt in range(ORDER_RETRY_MAX):
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda r=req: self._adapter.place_order_cash(
                        r.symbol, r.side,
                        qty=r.qty,
                        price=r.price,
                        order_type=r.order_type,
                        excg_id=excg_id,
                        env_dv=self._env,
                        dry_run=self._dry_run,
                        ord_dvsn_override=r.ord_dvsn_override,
                    ),
                )

                if result.get("status") == "ok":
                    self._consecutive_errors = 0
                    order_no = str(result.get("order_no") or "")
                    krx_org_no = str(result.get("krx_org_no") or "")

                    if self._dry_run:
                        order_no = order_no or f"DRY{int(time.time() * 1000) % 100000:05d}"

                    record.order_no   = order_no
                    record.krx_org_no = krx_org_no
                    record.status     = OrderStatus.SUBMITTED
                    self._records[order_no] = record

                    logger.info(
                        "Order submitted: %s %s %s qty=%d price=%.0f no=%s venue_policy=%s preferred=%s actual=%s",
                        req.symbol, req.side, req.reason, req.qty, req.price, order_no,
                        req.venue_policy.value, req.preferred_venue.value, req.actual_venue.value,
                    )
                    return order_no

                err = result.get("error") or result.get("msg1") or "unknown"
                logger.warning("Order attempt %d fail: %s — %s", attempt + 1, req.symbol, err)

                # VI/권한/종목 제한 → 재시도 없이 REJECTED
                if any(k in str(err) for k in ("VI", "거래정지", "권한", "사용자정보", "상한가", "하한가")):
                    record.status       = OrderStatus.REJECTED
                    record.error_msg    = err
                    record.reject_reason = err
                    logger.warning("Order REJECTED (no retry): %s — %s", req.symbol, err)
                    return None

            except Exception as exc:
                logger.warning("Order attempt %d exception: %s — %s", attempt + 1, req.symbol, exc)
                self._consecutive_errors += 1
                if self._consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                    if self._on_error:
                        self._on_error("consecutive_api_errors", exc)

            if attempt < ORDER_RETRY_MAX - 1:
                await asyncio.sleep(ORDER_RETRY_DELAY_SEC * (attempt + 1))

        record.status    = OrderStatus.REJECTED
        record.error_msg = "max retries exceeded"
        logger.error("Order failed after %d attempts: %s", ORDER_RETRY_MAX, req.symbol)
        return None

    # ── 시장가 즉시 제출 ─────────────────────────────────────────────────────

    async def submit_market(self, req: OrderRequest, emergency: bool = False) -> Optional[str]:
        """시장가 주문 (kill_switch / 미체결 청산 전환용)."""
        mreq = OrderRequest(
            symbol=req.symbol, side=req.side,
            qty=req.qty, price=0,
            order_type="market", reason=req.reason,
            ref_id=req.ref_id,
            market=req.market,
            position_type=req.position_type,
            order_session=req.order_session,
            ord_dvsn_override=req.ord_dvsn_override,
            listing_market=req.listing_market,
            execution_venue=req.execution_venue,
            preferred_venue=req.preferred_venue,
            actual_venue=req.actual_venue,
            venue_policy=req.venue_policy,
            market_session=req.market_session,
        )
        return await self.submit(mreq, emergency=emergency)

    @staticmethod
    def _excg_id_for_request(req: OrderRequest) -> str:
        if req.venue_policy == VenuePolicy.SOR_BEST_EXECUTION or req.preferred_venue == ExecutionVenue.SOR:
            return "SOR"
        if req.venue_policy == VenuePolicy.NXT_ONLY or req.preferred_venue == ExecutionVenue.NXT:
            return "NXT"
        return "KRX"

    # ── 체결 대기 ─────────────────────────────────────────────────────────────

    async def wait_fill(
        self, order_no: str, timeout: Optional[float] = None
    ) -> Optional[FillEvent]:
        """
        체결 대기. 진입/청산에 따라 타임아웃 자동 결정.
        타임아웃 시:
          - 진입 주문: 취소
          - 청산 주문: 취소 후 시장가 재주문
        """
        record = self._records.get(order_no)
        if not record:
            return None

        # dry_run: 즉시 전량 체결 (price=0인 시장가는 현재 기록가 or 기준가 사용)
        if self._dry_run:
            sim_price = record.req.price if record.req.price > 0 else record.expected_price
            if sim_price <= 0:
                sim_price = 10_000  # fallback — dry_run에서 가격 없을 때만
            record.apply_partial_fill(record.req.qty, sim_price)
            return record.to_fill_event()

        if self._dry_run_order:
            tick = self._market_snapshots.get(record.req.symbol)
            if tick is None:
                from .events import TickEvent
                px = record.req.price or record.expected_price or 10_000
                tick = TickEvent(
                    symbol=record.req.symbol,
                    price=px,
                    buy_vol_total=0,
                    sell_vol_total=0,
                    bid_qty=record.req.qty,
                    ask_qty=record.req.qty,
                    tick_vol=0,
                    acml_vol=0,
                    acml_tr_pbmn=0,
                    time_str="",
                    bid1_price=px,
                    ask1_price=px,
                )
            sim = self._simulator.simulate_fill(record.req, tick, timeout_sec=timeout)
            if sim.timeout or sim.filled_qty <= 0:
                record.status = OrderStatus.TIMED_OUT
                record.error_msg = sim.reason
                record.cancel_reason = "fill_timeout"
                logger.warning(
                    "DRY_RUN_ORDER simulated timeout: %s %s reason=%s",
                    record.req.symbol, order_no, sim.reason,
                )
                return None
            record.apply_partial_fill(sim.filled_qty, sim.actual_fill_price)
            return record.to_fill_event()

        # 타임아웃 결정
        if timeout is None:
            is_exit = record.req.reason in _EXIT_REASONS
            if record.req.order_session == "after_market":
                timeout = AFTER_MARKET_FILL_TIMEOUT
            else:
                timeout = EXIT_FILL_TIMEOUT if is_exit else ENTRY_FILL_TIMEOUT

        # H0STCNI9 Future가 등록된 경우 우선 사용
        if order_no in self._fill_futures:
            try:
                fill = await asyncio.wait_for(
                    asyncio.shield(self._fill_futures[order_no]), timeout=timeout
                )
                return fill
            except asyncio.TimeoutError:
                pass
        else:
            # REST 폴링 fallback
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                filled = await self._poll_fill(record)
                if filled:
                    return filled
                await asyncio.sleep(0.5)

        # 타임아웃 처리
        record.status = OrderStatus.TIMED_OUT
        record.cancel_reason = "fill_timeout"
        is_exit = record.req.reason in _EXIT_REASONS

        logger.warning(
            "Fill timeout: %s %s order_no=%s is_exit=%s position_type=%s session=%s",
            record.req.symbol, record.req.reason, order_no, is_exit,
            record.req.position_type.value, record.req.order_session or "regular",
        )

        await self.cancel_pending(order_no)

        if is_exit:
            # 청산 주문 미체결 → 시장가로 재주문 (필수)
            new_no = await self.submit_market(record.req)
            if new_no:
                new_rec = self._records.get(new_no)
                if new_rec and self._dry_run:
                    new_rec.apply_partial_fill(new_rec.req.qty, new_rec.req.price or 0)
                    return new_rec.to_fill_event()
                # 실전: 짧은 타임아웃으로 재대기
                return await self.wait_fill(new_no, timeout=3.0)

        # 진입 주문 미체결 → 부분체결 있으면 그것만 반환, 없으면 None
        if record.filled_qty > 0:
            return record.to_fill_event()

        return None

    # ── H0STCNI9 체결 통보 수신 ───────────────────────────────────────────────

    def on_fill_notify(self, order_no: str, qty: int, price: float) -> Optional[FillEvent]:
        """
        H0STCNI9 WebSocket 체결통보 수신 시 호출.
        부분체결이 여러 번 올 수 있으므로 apply_partial_fill()로 누적.
        BUG-29 FIX: FILLED 중복 수신 시 idempotent 처리.
        """
        record = self._records.get(order_no)
        if not record:
            return None

        # 이미 전량 체결된 주문 → 중복 통보 무시 (idempotency)
        if record.status == OrderStatus.FILLED:
            logger.debug("Duplicate fill notify ignored (already FILLED): %s", order_no)
            return record.to_fill_event()

        record.apply_partial_fill(qty, price)
        logger.debug(
            "Fill notify: %s qty=%d/%d price=%.0f status=%s",
            record.req.symbol, record.filled_qty, record.req.qty,
            price, record.status.value,
        )

        # Future 등록된 경우 체결 완료 시 set
        if record.status == OrderStatus.FILLED:
            fut = self._fill_futures.pop(order_no, None)
            if fut and not fut.done():
                fut.set_result(record.to_fill_event())
            return record.to_fill_event()

        return None  # 부분체결: 아직 대기 중

    def register_fill_future(self, order_no: str) -> asyncio.Future:
        """wait_fill()이 H0STCNI9 통보를 기다릴 Future 등록."""
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._fill_futures[order_no] = fut
        return fut

    # ── 미체결 취소 ───────────────────────────────────────────────────────────

    async def cancel_pending(self, order_no: str) -> bool:
        record = self._records.get(order_no)
        if not record:
            return False

        if self._dry_run:
            record.status = OrderStatus.CANCELED
            record.cancel_reason = record.cancel_reason or "dry_run_cancel"
            logger.info("DRY cancel: %s", order_no)
            return True
        if self._dry_run_order:
            record.status = OrderStatus.CANCELED
            record.cancel_reason = record.cancel_reason or "dry_run_order_cancel"
            logger.info("DRY_RUN_ORDER cancel: %s", order_no)
            return True

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._adapter.cancel_order(
                    krx_org_no=record.krx_org_no,
                    order_no=order_no,
                    symbol=record.req.symbol,
                    qty=record.req.qty,
                    cancel_all=True,
                    env_dv=self._env,
                ),
            )
            ok = result.get("status") == "ok"
            if ok:
                record.status = OrderStatus.CANCELED
                record.cancel_reason = record.cancel_reason or "user_cancel"
                logger.info("Order canceled: %s %s", record.req.symbol, order_no)
            else:
                logger.warning("Cancel failed: %s — %s", order_no, result.get("error"))
            return ok
        except Exception as exc:
            logger.error("Cancel exception: %s — %s", order_no, exc)
            self._consecutive_errors += 1
            return False

    # ── 슬리피지 체크 ─────────────────────────────────────────────────────────

    def check_slippage(self, expected: float, fill: float, side: str) -> tuple[bool, float]:
        """(초과 여부, 슬리피지 %). 양수 = 불리한 방향."""
        if expected <= 0:
            return False, 0.0
        diff = (fill - expected) / expected
        if side == "sell":
            diff = -diff
        exceeded = diff > MAX_SLIPPAGE_PCT
        if exceeded:
            logger.warning(
                "Slippage exceeded: exp=%.0f fill=%.0f diff=%.3f%%",
                expected, fill, diff * 100,
            )
        return exceeded, round(diff, 5)

    # ── 매수 가능 수량 ────────────────────────────────────────────────────────

    async def get_buyable_qty(self, symbol: str, price: float) -> int:
        if self._dry_run:
            return 9999
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._adapter.inquire_psbl_order(
                    symbol, price, order_type="limit", env_dv=self._env,
                ),
            )
            if result.get("status") == "ok":
                return int(result.get("nrcvb_buy_qty") or 0)
        except Exception as exc:
            logger.warning("get_buyable_qty error: %s", exc)
            self._consecutive_errors += 1
        return 0

    def update_market_snapshot(self, tick: Any) -> None:
        symbol = str(getattr(tick, "symbol", "") or "")
        if symbol:
            self._market_snapshots[symbol] = tick

    # ── 조회 ─────────────────────────────────────────────────────────────────

    def get_record(self, order_no: str) -> Optional[OrderRecord]:
        return self._records.get(order_no)

    def active_order_nos(self) -> list[str]:
        """SUBMITTED / PARTIALLY_FILLED 상태인 order_no 목록."""
        return [
            no for no, r in self._records.items()
            if r.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)
        ]

    # ── REST 폴링 fallback ────────────────────────────────────────────────────

    async def _poll_fill(self, record: OrderRecord) -> Optional[FillEvent]:
        """
        H0STCNI9 누락 시 REST fallback으로 체결 확인.
        BUG-29 FIX: sell side도 폴링 지원.
        """
        loop = asyncio.get_event_loop()
        try:
            # 1차: 주문 체결 내역 직접 조회 (KIS inquire_order_ccld, 어댑터가 지원 시)
            if hasattr(self._adapter, "inquire_order_ccld"):
                ccld = await loop.run_in_executor(
                    None,
                    lambda: self._adapter.inquire_order_ccld(
                        order_no=record.order_no, env_dv=self._env,
                    ),
                )
                if ccld.get("status") == "ok":
                    filled_qty  = int(ccld.get("filled_qty") or 0)
                    avg_price   = float(ccld.get("avg_fill_price") or 0)
                    if filled_qty > 0 and avg_price > 0:
                        logger.debug(
                            "REST ccld fallback: %s filled=%d price=%.0f",
                            record.req.symbol, filled_qty, avg_price,
                        )
                        record.apply_partial_fill(filled_qty, avg_price)
                        return record.to_fill_event() if record.status == OrderStatus.FILLED else None

            # 2차: 잔고 조회 기반 fallback
            result = await loop.run_in_executor(
                None,
                lambda: self._adapter.inquire_balance(env_dv=self._env),
            )
            if result.get("status") != "ok":
                return None

            holdings = {h.get("symbol"): h for h in (result.get("holdings") or [])}

            if record.req.side == "buy":
                h = holdings.get(record.req.symbol)
                if h and int(h.get("qty") or 0) >= record.req.qty:
                    avg = float(h.get("avg_price") or record.req.price)
                    record.apply_partial_fill(record.req.qty, avg)
                    logger.debug("REST buy fallback OK: %s qty=%d", record.req.symbol, record.req.qty)
                    return record.to_fill_event()

            elif record.req.side == "sell":
                # sell 폴링: 보유 잔고에 해당 종목이 없거나 qty가 충분히 감소했으면 체결로 간주
                pre_qty = self._pre_sell_qty.pop(record.order_no, None)
                h = holdings.get(record.req.symbol)
                cur_qty = int(h.get("qty") or 0) if h else 0

                if pre_qty is not None:
                    sold = pre_qty - cur_qty
                    if sold >= record.req.qty:
                        # 매도 체결 확인 — fill_price는 avg_price 근사
                        fill_p = record.req.price or (float(h.get("avg_price") or 0) if h else 0)
                        if fill_p <= 0:
                            fill_p = record.expected_price
                        logger.debug(
                            "REST sell fallback OK: %s sold=%d price=%.0f",
                            record.req.symbol, sold, fill_p,
                        )
                        record.apply_partial_fill(record.req.qty, fill_p)
                        return record.to_fill_event() if record.status == OrderStatus.FILLED else None
                else:
                    # pre_qty 미기록 시: 보유 잔고에 없으면 전량 매도로 추정
                    if record.req.symbol not in holdings:
                        fill_p = record.expected_price or record.req.price
                        logger.debug(
                            "REST sell fallback (no holdings): %s price=%.0f",
                            record.req.symbol, fill_p,
                        )
                        record.apply_partial_fill(record.req.qty, fill_p)
                        return record.to_fill_event() if record.status == OrderStatus.FILLED else None

        except Exception as exc:
            logger.debug("_poll_fill error: %s", exc)
        return None

    def _record_pre_sell_qty(self, order_no: str, qty: int) -> None:
        """sell 주문 제출 전 현재 보유수량 기록 (REST fallback용)."""
        self._pre_sell_qty[order_no] = qty
