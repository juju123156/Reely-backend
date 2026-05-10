"""ScalpingBot — production-grade 자동매매 봇.

상태머신:
  READY → RUNNING → STOPPING → TERMINATED
                 ↘ PAUSED ↗

루프 정책:
  전략 루프  (RUNNING only):   _tick_dispatcher, _scan_loop, _time_loop, _risk_loop
  실행 루프  (RUNNING+STOPPING): _ws_watchdog, _stopping_monitor
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import signal
import time
from collections import Counter
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .config import ScalpingBotConfig
from .constants import (
    MARKET_OPEN, NO_NEW_ENTRY_TIME, FORCE_CLOSE_TIME, SOFT_CLOSE_TIME,
    CLOSING_AUCTION_START,
    SCAN_WINDOW_END, MORNING_SNAPSHOT_TIME,
    CLOSE_BET_START_TIME, CLOSE_BET_END_TIME, CLOSE_BET_SCAN_INTERVAL_SEC,
    AFTER_MARKET_START_TIME, AFTER_MARKET_END_TIME,
    NEXT_OPEN_EXIT_START, NEXT_DAY_EXIT_DEADLINE,
    NO_ENTRY_UNTIL, CONSERVATIVE_ENTRY_UNTIL, CONSERVATIVE_SCORE_BOOST,
    COMMISSION_RATE, TAX_RATE_KOSDAQ,
    MAX_ENTRY_SPREAD_PCT, MIN_ATR_COST_RATIO,
    EXPECTED_ENTRY_SLIPPAGE_PCT, EXPECTED_EXIT_SLIPPAGE_PCT, MIN_PROFIT_COST_RATIO,
    CIRCUIT_BREAKER_THRESHOLD,
    ATR_TRAIL_MULTIPLIER,
    MAX_RISK_STORE_ERRORS, MAX_POS_STORE_ERRORS,
    STOPPING_WS_BACKOFF_CAP, WS_RESUB_COOLDOWN_SECS,
    CB_RESUME_POLL_SECS, SNAPSHOT_VERSION,
    BALANCE_API_TIMEOUT_SEC,
    SHALLOW_ENTRY_SCORE,
)
from .after_market_engine import AfterMarketEngine
from .alerts import AlertEvent, OperationalAlertSink
from .closing_bet_results import ClosingBetResultStore, gap_pct
from .closing_bet_scanner import CloseBetCandidate, CloseBetScanner
from .events import FillEvent, OrderRequest, TickEvent
from .expected_edge import ExpectedEdgeInputs, ExpectedEdgeModel
from .live_guard import LiveKillSwitchGuard
from .market_phase import MarketPhase, MarketPhaseResolver
from .market_regime import (
    MarketRegime, MarketRegimeAnalyzer, StrategyBlockReason, KOSPI_LARGE_CAP_UNIVERSE,
)
from .market_scanner import MarketScanner
from .macro_overnight_feed import MacroOvernightFeedEngine
from .macro_risk_model import MacroRiskModel
from .microstructure_engine import QuoteEvent, RealtimeMicrostructureEngine, TradePrint
from .morning_decision_engine import MorningAction, MorningDecisionInput, MorningPositionDecisionEngine
from .opening_candle_engine import OpeningCandleEngine
from .nxt_market import build_nxt_context, choose_routing, detect_venue_capability, evaluate_nxt_pre
from .overnight_engine import OvernightAction, OvernightEngine
from .order_executor import OrderExecutor, OrderStatus
from .orderbook_pressure import (
    DepthFillSimulator,
    OrderbookPressureFilter,
    OrderbookStabilityObserver,
    snapshot_from_tick,
)
from .position_manager import PositionManager, PositionPhase
from .position_type import PositionType, ttl_for, infer_from_recovery_time
from .reports import build_daily_strategy_report
from .regime_runtime import (
    ExecutionQualityGate,
    ExecutionQualityInputs,
    ExecutionQualitySnapshot,
    LatencyState,
    QuoteHealthMonitor,
    QuoteHealthSnapshot,
    RegimeInputs,
    RegimeScoreEngine,
    RegimeSnapshot,
    RuntimePermissionGate,
    RuntimeRegime,
)
from .risk_manager import RiskManager
from .shadow_trading import ShadowTradingEngine
from .gatekeeper_replay import GatekeeperReplayStore, GatekeeperSnapshot
from .signal_engine import SignalEngine
from .state_store import BaseStateStore, make_state_store
from .strategy_journal import StrategySignalJournal
from .strategy_promotion import PromotionState, StrategyPromotionGate
from .strategy_router import IntradayStrategyRouter
from .strategy_types import StrategyContext, StrategySignal
from .trade_journal import TradeJournal
from .venue import ExecutionVenue, ListingMarket, MarketSession, VenueCapability, VenuePolicy, enum_value, listing_market_from_legacy
from .funnel_sentinel import build_buy_funnel_sentinel_report
from .holding_exit_sentinel import build_holding_exit_sentinel_report
from .missed_entry_counterfactual import build_missed_entry_counterfactual

logger = logging.getLogger(__name__)

# STOPPING 타임아웃: 이 시간 안에 전량 청산 안 되면 emergency reconcile
_STOPPING_TIMEOUT_SECS = 30.0
# STOPPING 중 포지션/미체결 확인 주기
_STOPPING_POLL_SECS = 0.5


# ── BotStatus 상태머신 ────────────────────────────────────────────────────────

class BotStatus(Enum):
    READY      = "ready"
    RUNNING    = "running"
    PAUSED     = "paused"       # 신규 진입 중단, 포지션 유지
    STOPPING   = "stopping"     # Kill Switch 발동 — 전략 중단, 청산 진행
    STOPPED    = "stopped"      # 정상 종료
    TERMINATED = "terminated"   # STOPPING 완료 — 전량 청산 확인


# ── Kill Switch 트리거 원인 ───────────────────────────────────────────────────

class KillReason:
    SIGNAL             = "signal"
    FORCE_CLOSE_TIME   = "force_close_time"
    CONSECUTIVE_ERRORS = "consecutive_api_errors"
    WS_DISCONNECT      = "websocket_disconnect"
    PRICE_QUERY_FAIL   = "price_query_fail"
    ORDER_TIMEOUT      = "order_timeout"
    LIVE_GUARD         = "live_guard"
    STATE_SYNC_FAIL    = "state_sync_fail"
    DAILY_LOSS         = "daily_loss_limit"
    CONSECUTIVE_LOSS   = "consecutive_loss_limit"   # BUG-26 FIX
    KOSDAQ_HALT        = "kosdaq_index_halt"         # BUG-26 FIX
    CIRCUIT_BREAKER    = "circuit_breaker"
    MANUAL             = "manual"


def _is_active(status: BotStatus) -> bool:
    """전략+실행 루프가 살아있어야 할 상태."""
    return status in (BotStatus.RUNNING, BotStatus.PAUSED)


def _is_execution_active(status: BotStatus) -> bool:
    """실행 채널(WS watchdog, stopping monitor)이 살아있어야 할 상태."""
    return status in (BotStatus.RUNNING, BotStatus.PAUSED, BotStatus.STOPPING)


class ScalpingBot:
    """
    컴포넌트 이벤트 흐름:
      WebSocket (H0STCNT0)
        → enqueue_tick()
        → _tick_dispatcher()      [RUNNING only]
        → SignalEngine.process_tick()
        → PositionManager.check_exits()
        → RiskManager.update_unrealized()

      _scan_loop() 3초             [RUNNING only]
      _time_loop() 1초             [RUNNING only]
      _risk_loop() 10초            [RUNNING only]

      _ws_watchdog() 5초           [RUNNING + STOPPING]
        stale tick → reconnect (degraded mode during STOPPING)

      _stopping_monitor()          [항상 실행, STOPPING 이벤트 대기]
        liquidate_all()
        partial fill 추적
        timeout(30s) → emergency_reconcile()
        position==0 & pending==0 → TERMINATED

    리스크 우선 원칙:
    - "잘못된 신호" 보다 "상태 동기화 실패"가 더 위험
    - STOPPING 진입 즉시 전략 중단
    - execution channel은 마지막 체결까지 유지
    """

    def __init__(self, config: Optional[ScalpingBotConfig] = None) -> None:
        self._cfg = config or ScalpingBotConfig()
        self._status = BotStatus.READY
        self._kill_event = asyncio.Event()       # TERMINATED 도달 시 set
        self._stopping_event = asyncio.Event()   # STOPPING 진입 시 set
        self._kill_reason: str = ""
        self._stopping_ts: float = 0.0

        # ── 컴포넌트 ──────────────────────────────────────────────────────────
        self._adapter: Any = None
        self._scanner: Optional[MarketScanner] = None
        self._close_bet_scanner: Optional[CloseBetScanner] = None
        self._after_market_engine: Optional[AfterMarketEngine] = None
        self._signal_engine: Optional[SignalEngine] = None
        self._position_mgr: Optional[PositionManager] = None
        self._risk_mgr: Optional[RiskManager] = None
        self._executor: Optional[OrderExecutor] = None
        self._store: Optional[BaseStateStore] = None
        self._journal: TradeJournal = TradeJournal()
        self._closing_bet_results = ClosingBetResultStore()
        self._venue_capability: VenueCapability = VenueCapability()
        self._overnight_engine = OvernightEngine()
        self._microstructure_engine = RealtimeMicrostructureEngine()
        self._opening_candle_engine = OpeningCandleEngine()
        self._macro_feed_engine = MacroOvernightFeedEngine()
        self._macro_risk_model = MacroRiskModel()
        self._morning_decision_engine = MorningPositionDecisionEngine()
        self._shadow_engine = ShadowTradingEngine()
        self._strategy_router = IntradayStrategyRouter()
        self._strategy_journal = StrategySignalJournal()
        self._promotion_gate = StrategyPromotionGate()
        self._live_guard = LiveKillSwitchGuard()
        self._phase_resolver = MarketPhaseResolver()
        self._alert_sink = OperationalAlertSink()
        self._regime_score_engine = RegimeScoreEngine()
        self._execution_quality_gate = ExecutionQualityGate()
        self._runtime_permission_gate = RuntimePermissionGate()
        self._expected_edge_model = ExpectedEdgeModel()
        self._quote_health_monitor = QuoteHealthMonitor()
        self._gatekeeper_replay = GatekeeperReplayStore()
        self._orderbook_filter = OrderbookPressureFilter()
        self._orderbook_stability_observer = OrderbookStabilityObserver()
        self._depth_fill_simulator = DepthFillSimulator()
        self._runtime_regime_snapshot: RegimeSnapshot | None = None
        self._execution_quality_snapshot: ExecutionQualitySnapshot | None = None
        self._quote_health_snapshot: QuoteHealthSnapshot | None = None
        self._last_runtime_permission: dict[str, dict] = {}
        self._last_alerted_runtime_permission: dict[str, tuple[str, str]] = {}
        self._reconcile_mismatch_count: int = 0
        self._reconcile_failure_count: int = 0
        self._broker_reconcile_blocked: bool = False

        # ── 중복 진입/청산 방지 ───────────────────────────────────────────────
        # BUG-40 FIX: entry와 exit lock 분리 → exit이 entry 대기하지 않음
        self._entry_locks: dict[str, asyncio.Lock] = {}
        self._exit_locks: dict[str, asyncio.Lock] = {}
        self._symbol_locks: dict[str, asyncio.Lock] = {}  # 하위 호환 유지
        self._active_order_symbols: set[str] = set()
        self._cancel_entry_for: set[str] = set()  # exit 발생 시 진행 중 entry 취소 플래그

        # ── WebSocket 상태 감시 ───────────────────────────────────────────────
        self._ws_subscriber: Any = None
        self._last_tick_ts: float = 0.0
        self._ws_stale_secs: float = 30.0
        self._ws_reconnect_count: int = 0
        self._ws_symbols: list[str] = []

        # ── 시장 레짐 ────────────────────────────────────────────────────────
        self._regime_analyzer: MarketRegimeAnalyzer = MarketRegimeAnalyzer()

        # ── 큐 / 루프 ─────────────────────────────────────────────────────────
        self._tick_queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._watchlist: set[str] = set()

        # ── 가격 캐시 (BUG-25 FIX: 종목별 최신가) ────────────────────────────
        self._price_cache: dict[str, float] = {}

        # ── 장애 내성 카운터 ─────────────────────────────────────────────────
        # BUG-27 FIX: Redis 일시 장애로 즉시 kill_switch 방지
        self._risk_store_errors: int = 0
        self._pos_store_errors: int = 0

        # ── WS 재구독 쿨다운 (BUG-17 FIX) ────────────────────────────────────
        self._ws_last_resub_ts: float = 0.0

        # ── 서킷브레이커 상태 (BUG-37) ───────────────────────────────────────
        self._market_halted: bool = False  # True이면 주문 차단, 재개 대기

        # ── 오전 스냅샷 (점심 전략 백테스트 데이터) ──────────────────────────
        self._morning_snapshot_taken: bool = False
        self._candidate_cache: dict = {}  # symbol → SymbolCandidate
        self._last_strategy_signal_counts: dict[str, int] = {}
        self._shadow_entry_counts: dict[str, int] = {}
        self._live_order_attempt_count: int = 0
        self._live_fill_count: int = 0
        self._freshness_samples: int = 0
        self._stale_feature_samples: int = 0
        self._daily_strategy_report_done: bool = False

        # ── Dashboard / 진단 카운터 ───────────────────────────────────────────
        self._reject_reason_counter: Counter = Counter()   # reason → 누적 횟수
        self._dashboard_last_funnel_ts: float = 0.0        # buy_funnel_sentinel 마지막 실행
        self._dashboard_last_counterfactual_ts: float = 0.0  # missed_entry_counterfactual 마지막 실행
        self._dashboard_last_exit_sentinel_ts: float = 0.0   # holding_exit_sentinel 마지막 실행
        self._dashboard_log_path: Path = Path("data/dashboard")

        # ── Expected Edge Model 캘리브레이션 (어제 shadow stats 로드) ─────────
        self._historical_strategy_stats: dict[str, dict] = self._load_historical_strategy_stats()

        # ── 종가베팅 익일 청산 관리 ───────────────────────────────────────────
        self._close_bet_exit_done: bool = False  # True이면 NextOpenExit 완료
        self._force_close_skip_logged: bool = False

    # ═══════════════════════════════════════════════════════════════════════════
    # 진입점
    # ═══════════════════════════════════════════════════════════════════════════

    async def run(self, symbols: Optional[list[str]] = None) -> None:
        """메인 루프. setup → gather(all loops) → teardown."""
        await self._setup(symbols)
        self._status = BotStatus.RUNNING
        logger.info(
            "[READY→RUNNING] dry=%s env=%s symbols=%s",
            self._cfg.strategy.dry_run, self._cfg.broker.env, symbols,
        )

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(
                    self.kill_switch(KillReason.SIGNAL)
                ),
            )

        try:
            await asyncio.gather(
                # ── 전략 루프 (RUNNING only) ──────────────────────────────────
                self._tick_dispatcher(),
                self._scan_loop(),
                self._time_loop(),
                self._risk_loop(),
                self._account_loop(),
                self._strategy_schedule_loop(),
                self._index_monitor_loop(),
                self._closing_bet_loop(),
                # ── 종가베팅 익일 청산 (CLOSE_BET 존재 시 활성화) ──────────────
                self._next_open_exit_engine(),
                self._after_market_engine_loop(),
                # ── 운영 진단 루프 (30초 dashboard + 10분 funnel sentinel) ────
                self._dashboard_loop(),
                # ── 실행 루프 (RUNNING + STOPPING) ───────────────────────────
                self._ws_watchdog(),
                self._stopping_monitor(),
                # ── 종료 대기 ─────────────────────────────────────────────────
                self._wait_for_kill(),
            )
        except asyncio.CancelledError:
            pass
        finally:
            await self._teardown()

    # ═══════════════════════════════════════════════════════════════════════════
    # Kill Switch — 트리거만 담당; 실제 청산은 _stopping_monitor
    # ═══════════════════════════════════════════════════════════════════════════

    async def kill_switch(self, reason: str = KillReason.MANUAL) -> None:
        """
        STOPPING 상태 전이 트리거.
        - 전략 루프 즉시 차단
        - _stopping_monitor 가 청산/모니터링/TERMINATED 전이 담당
        """
        if self._status in (BotStatus.STOPPING, BotStatus.TERMINATED):
            return  # 중복 호출 방지

        prev = self._status.value
        self._status = BotStatus.STOPPING
        self._stopping_ts = time.monotonic()

        # BUG-26 FIX: RiskManager halt 원인에 따라 정확한 kill_reason 매핑
        if reason == KillReason.DAILY_LOSS and self._risk_mgr:
            ht = self._risk_mgr.halt_type
            if ht == "consecutive_loss":
                reason = KillReason.CONSECUTIVE_LOSS
            elif ht == "kosdaq_halt":
                reason = KillReason.KOSDAQ_HALT
        self._kill_reason = reason

        n_pos = len(self._position_mgr.active_positions()) if self._position_mgr else 0
        n_pending = len(self._executor.active_order_nos()) if self._executor else 0
        logger.critical(
            "[%s→STOPPING] reason=%s positions=%d pending_orders=%d",
            prev, reason, n_pos, n_pending,
        )
        self._emit_alert(
            kind="kill_switch",
            severity="critical",
            message=f"kill switch triggered: {reason}",
            payload={
                "previous_status": prev,
                "reason": reason,
                "positions": n_pos,
                "pending_orders": n_pending,
            },
        )

        # _stopping_monitor 깨우기
        self._stopping_event.set()

    def trigger_kill_switch_sync(self, reason: str, exc: Exception) -> None:
        """스레드에서 호출 가능한 동기 Kill Switch 트리거."""
        logger.error("Kill switch triggered (sync): %s — %s", reason, exc)
        try:
            self._live_guard.observe_api_error()
        except Exception:
            pass
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.kill_switch(reason))
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # STOPPING 모니터 (실행 루프)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _stopping_monitor(self) -> None:
        """
        STOPPING 이벤트 대기 → 전량 청산 → TERMINATED.

        RUNNING 중에는 잠자고 있다가 kill_switch()가 호출되면 깨어남.
        WS 체결통보 + REST fallback 모두 활용.
        """
        # STOPPING 트리거 대기
        await self._stopping_event.wait()

        if self._status not in (BotStatus.STOPPING,):
            return   # 이미 TERMINATED/STOPPED

        n_pos = len(self._position_mgr.active_positions()) if self._position_mgr else 0
        logger.critical(
            "[STOPPING] Monitor started. positions=%d reason=%s",
            n_pos, self._kill_reason,
        )

        # 1. 전량 시장가 청산 제출
        await self._liquidate_all(self._kill_reason)

        _last_liquidated_syms: set[str] = set()  # BUG-33: 이미 청산 제출한 심볼 추적

        # 2. 체결 완료 / timeout 까지 대기
        while True:
            n_pos     = len(self._liquidation_required_positions(self._kill_reason))
            n_pending = len(self._executor.active_order_nos()) if self._executor else 0

            if n_pos == 0 and n_pending == 0:
                logger.info(
                    "[STOPPING] All positions cleared. positions=0 pending=0"
                )
                break

            elapsed = time.monotonic() - self._stopping_ts
            if elapsed > _STOPPING_TIMEOUT_SECS:
                logger.critical(
                    "[STOPPING] Timeout %.0fs reached. positions=%d pending=%d — emergency reconcile",
                    elapsed, n_pos, n_pending,
                )
                await self._emergency_reconcile()
                break

            # BUG-33 FIX: STOPPING 중 entry fill로 새 포지션 생성 시 즉시 재청산
            if self._position_mgr:
                current_syms = set(
                    self._liquidation_required_positions(self._kill_reason).keys()
                )
                new_syms = current_syms - _last_liquidated_syms
                if new_syms:
                    logger.warning(
                        "[STOPPING] New positions detected post-liquidate: %s — re-liquidating",
                        new_syms,
                    )
                    for sym in new_syms:
                        pos = self._position_mgr.get_position(sym)
                        if pos and pos.remaining_qty > 0:
                            asyncio.create_task(
                                self._liquidate_position(sym, pos.remaining_qty)
                            )
                        _last_liquidated_syms.add(sym)

            logger.debug(
                "[STOPPING] Waiting... positions=%d pending=%d elapsed=%.1fs",
                n_pos, n_pending, elapsed,
            )
            await asyncio.sleep(_STOPPING_POLL_SECS)

        # 3. TERMINATED 전이
        await self._finalize_stopping()

    def _liquidation_required_positions(self, reason: str = "") -> dict[str, Any]:
        """Kill reason 기준으로 STOPPING 중 실제 청산해야 할 포지션만 반환."""
        if not self._position_mgr:
            return {}

        positions = dict(self._position_mgr.active_positions())
        if reason == KillReason.FORCE_CLOSE_TIME:
            return {
                symbol: pos
                for symbol, pos in positions.items()
                if (
                    getattr(pos, "position_type", PositionType.UNKNOWN)
                    != PositionType.CLOSE_BET
                )
            }
        return positions

    async def _liquidate_all(self, reason: str = "") -> None:
        """보유 포지션 전량 시장가 청산 — concurrent 제출."""
        if not self._position_mgr or not self._executor:
            return

        positions = list(self._liquidation_required_positions(reason).items())
        if not positions:
            logger.info("[STOPPING] No positions to liquidate.")
            return

        logger.warning(
            "[STOPPING] Liquidating %d positions: %s",
            len(positions), [s for s, _ in positions],
        )

        liquidation_targets = [
            (symbol, pos)
            for symbol, pos in positions
            if pos.remaining_qty > 0
        ]
        tasks = [
            self._liquidate_position(symbol, pos.remaining_qty)
            for symbol, pos in liquidation_targets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sym, result in zip([s for s, _ in liquidation_targets], results):
            if isinstance(result, Exception):
                logger.error("[STOPPING] Liquidate %s failed: %s", sym, result)

    async def _liquidate_position(self, symbol: str, qty: int) -> None:
        """단일 종목 시장가 청산 — partial fill 반복 처리.
        BUG-30 FIX: emergency=True로 NO_ORDER_AFTER 이후에도 청산 시도.
        """
        if symbol not in self._exit_locks:
            self._exit_locks[symbol] = asyncio.Lock()

        async with self._exit_locks[symbol]:
            remaining = qty
            attempt = 0
            MAX_ATTEMPTS = 3

            while remaining > 0 and attempt < MAX_ATTEMPTS:
                attempt += 1
                req = OrderRequest(
                    symbol=symbol, side="sell",
                    qty=remaining, price=0,
                    order_type="market", reason="kill_switch",
                )
                # BUG-30 FIX: emergency=True — STOPPING 중 NO_ORDER_AFTER 이후에도 청산 허용
                order_no = await self._executor.submit(req, emergency=True)
                if not order_no:
                    logger.error(
                        "[STOPPING] %s sell submit failed attempt=%d", symbol, attempt
                    )
                    await asyncio.sleep(1.0)
                    continue

                fill = await self._executor.wait_fill(order_no, timeout=8.0)
                if not fill:
                    logger.warning(
                        "[STOPPING] %s fill timeout attempt=%d — retrying", symbol, attempt
                    )
                    await asyncio.sleep(0.5)
                    # 실제 잔량 재조회
                    remaining = await self._query_broker_qty(symbol)
                    continue

                # 체결 반영
                pos = self._position_mgr.on_fill_exit(fill)
                if pos:
                    net_pnl = (fill.fill_price - pos.avg_price) * fill.filled_qty
                    net_pnl -= fill.commission + fill.tax
                    self._risk_mgr.record_trade(
                        symbol=symbol,
                        realized_pnl=net_pnl,
                        commission=fill.commission,
                        is_partial=(fill.filled_qty < qty),
                    )
                    rec = self._journal.record_exit(
                        symbol=symbol, order_no=fill.order_no,
                        fill_price=fill.fill_price,
                        expected_price=fill.fill_price,
                        qty=fill.filled_qty,
                        commission=fill.commission, tax=fill.tax,
                        slippage_pct=0.0, net_pnl=net_pnl,
                        reason="kill_switch",
                    )
                    if self._store:
                        try:
                            await self._store.log_trade({**rec.to_dict(), "type": "exit"})
                        except Exception:
                            pass

                    remaining_after = getattr(pos, "remaining_qty", 0)
                    logger.warning(
                        "[STOPPING] %s partial=%s filled=%d remaining=%d pnl=%.0f",
                        symbol, fill.filled_qty < qty,
                        fill.filled_qty, remaining_after, net_pnl,
                    )

                    if pos.phase == PositionPhase.CLOSED:
                        if self._store:
                            try:
                                await self._store.delete_position(symbol)
                            except Exception:
                                pass
                        remaining = 0
                    else:
                        remaining = remaining_after
                else:
                    remaining = 0  # position already gone

            if remaining > 0:
                logger.critical(
                    "[STOPPING] %s still has remaining_qty=%d after %d attempts",
                    symbol, remaining, MAX_ATTEMPTS,
                )

    async def _emergency_reconcile(self) -> None:
        """
        STOPPING timeout 후 비상 조치.
        1. 미체결 주문 전체 취소
        2. broker 실제 잔고 조회
        3. 잔여 포지션 재청산 시도
        4. 내부 상태와 broker 상태 동기화
        """
        logger.critical("[STOPPING] Emergency reconciliation started.")

        if not self._executor or not self._position_mgr:
            return

        loop = asyncio.get_event_loop()

        # Step 1: 미체결 주문 전체 취소
        pending_nos = self._executor.active_order_nos()
        logger.warning(
            "[STOPPING] Cancelling %d pending orders: %s", len(pending_nos), pending_nos
        )
        for order_no in pending_nos:
            try:
                await self._executor.cancel_pending(order_no)
            except Exception as exc:
                logger.error("[STOPPING] Cancel %s failed: %s", order_no, exc)

        # Step 2: broker 실제 잔고 조회
        broker_holdings: dict[str, int] = {}
        broker_query_ok = False
        try:
            bal = await loop.run_in_executor(
                None,
                lambda: self._adapter.inquire_balance(env_dv=self._cfg.broker.env),
            )
            if bal.get("status") == "ok":
                for h in (bal.get("holdings") or []):
                    qty = int(h.get("qty") or 0)
                    if qty > 0:
                        broker_holdings[h["symbol"]] = qty
                broker_query_ok = True
                logger.warning(
                    "[STOPPING] Broker actual holdings after cancel: %s", broker_holdings
                )
        except Exception as exc:
            logger.error("[STOPPING] Broker balance query failed: %s", exc)

        # Step 3: 내부 포지션과 broker 잔고 sync + 재청산
        internal_positions = self._liquidation_required_positions(self._kill_reason)

        if broker_query_ok:
            # BUG-06 FIX: broker 조회 성공 시에만 broker를 정답으로 사용
            all_symbols = set(list(internal_positions.keys()) + list(broker_holdings.keys()))

            for sym in all_symbols:
                active_pos = self._position_mgr.get_position(sym)
                if (
                    self._kill_reason == KillReason.FORCE_CLOSE_TIME
                    and active_pos
                    and active_pos.position_type == PositionType.CLOSE_BET
                ):
                    continue

                broker_qty = broker_holdings.get(sym, 0)
                internal_pos = internal_positions.get(sym)
                internal_qty = internal_pos.remaining_qty if internal_pos else 0

                if broker_qty != internal_qty:
                    logger.critical(
                        "[STOPPING] Mismatch %s: internal=%d broker=%d — using broker qty",
                        sym, internal_qty, broker_qty,
                    )
                    if internal_pos:
                        internal_pos.remaining_qty = broker_qty

                if broker_qty > 0:
                    logger.warning(
                        "[STOPPING] Re-liquidating %s qty=%d (emergency)", sym, broker_qty
                    )
                    try:
                        await self._liquidate_position(sym, broker_qty)
                    except Exception as exc:
                        logger.critical(
                            "[STOPPING] Emergency liquidate %s failed: %s — MANUAL ACTION REQUIRED",
                            sym, exc,
                        )

            # Step 4: 남은 내부 포지션 강제 제거 (broker에도 없으면)
            for sym, pos in list(self._position_mgr.active_positions().items()):
                if sym not in broker_holdings:
                    logger.warning(
                        "[STOPPING] %s not in broker — forcing CLOSED internally", sym
                    )
                    pos.phase = PositionPhase.CLOSED
                    if self._store:
                        try:
                            await self._store.delete_position(sym)
                        except Exception:
                            pass
        else:
            # BUG-06 FIX: broker 조회 실패 시 내부 포지션만으로 재청산 시도 (빈 dict로 전량 삭제 방지)
            logger.error(
                "[STOPPING] Broker query failed — re-liquidating %d internal positions",
                len(internal_positions),
            )
            for sym, pos in internal_positions.items():
                if pos.remaining_qty > 0:
                    try:
                        await self._liquidate_position(sym, pos.remaining_qty)
                    except Exception as exc:
                        logger.critical(
                            "[STOPPING] Emergency liquidate %s failed: %s — MANUAL ACTION REQUIRED",
                            sym, exc,
                        )

        logger.critical("[STOPPING] Emergency reconciliation complete.")

    async def _finalize_stopping(self) -> None:
        """STOPPING → TERMINATED 전이 + StateStore 기록."""
        n_pos     = len(self._position_mgr.active_positions()) if self._position_mgr else 0
        n_pending = len(self._executor.active_order_nos()) if self._executor else 0
        elapsed   = time.monotonic() - self._stopping_ts

        self._status = BotStatus.TERMINATED
        logger.critical(
            "[STOPPING→TERMINATED] reason=%s positions=%d pending=%d elapsed=%.1fs",
            self._kill_reason, n_pos, n_pending, elapsed,
        )

        if self._store:
            try:
                await self._store.save_risk({
                    "kill_switch": True,
                    "reason": self._kill_reason,
                    "terminated_at": time.time(),
                    "final_positions": n_pos,
                    "final_pending_orders": n_pending,
                    "stopping_elapsed_secs": round(elapsed, 1),
                })
            except Exception as exc:
                logger.error("[TERMINATED] save_risk failed: %s", exc)

        self._kill_event.set()

    async def _query_broker_qty(self, symbol: str) -> int:
        """broker 실제 보유 수량 조회 (partial fill 재시도 시 사용)."""
        loop = asyncio.get_event_loop()
        try:
            bal = await loop.run_in_executor(
                None,
                lambda: self._adapter.inquire_balance(env_dv=self._cfg.broker.env),
            )
            if bal.get("status") == "ok":
                for h in (bal.get("holdings") or []):
                    if h.get("symbol") == symbol:
                        return int(h.get("qty") or 0)
        except Exception as exc:
            logger.warning("[STOPPING] _query_broker_qty %s failed: %s", symbol, exc)
        return 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 셋업 / 티어다운
    # ═══════════════════════════════════════════════════════════════════════════

    async def _setup(self, symbols: Optional[list[str]] = None) -> None:
        from src.brokers import get_broker_adapter

        cfg = self._cfg
        self._adapter = get_broker_adapter(cfg.broker.name)
        loop = asyncio.get_event_loop()

        self._store = await make_state_store(cfg)

        capital = 0.0
        try:
            bal = await loop.run_in_executor(
                None,
                lambda: self._adapter.inquire_balance(env_dv=cfg.broker.env),
            )
            if bal.get("status") == "ok":
                capital = float((bal.get("summary") or {}).get("deposit") or 0)
                logger.info("Capital: %.0f", capital)
        except Exception as exc:
            logger.warning("Balance check failed: %s", exc)

        self._signal_engine = SignalEngine()
        self._position_mgr  = PositionManager()
        self._risk_mgr      = RiskManager(capital=capital)
        self._executor      = OrderExecutor(
            adapter=self._adapter,
            env=cfg.broker.env,
            dry_run=cfg.strategy.dry_run,
            dry_run_order=cfg.strategy.dry_run_order,
            on_error=self.trigger_kill_switch_sync,
        )
        self._scanner = MarketScanner(self._adapter, env=cfg.broker.env)
        self._venue_capability = detect_venue_capability(self._adapter, env=cfg.broker.env)
        logger.info(
            "[NXT_CAPABILITY] data=%s order=%s sor=%s vts=%s fallback=%s",
            self._venue_capability.nxt_data_available,
            self._venue_capability.nxt_order,
            self._venue_capability.sor_order,
            self._venue_capability.vts_nxt_supported,
            not self._venue_capability.nxt_data_available,
        )
        self._close_bet_scanner = CloseBetScanner(
            self._adapter,
            self._signal_engine,
            self._position_mgr,
            env=cfg.broker.env,
            market_scanner=self._scanner,
        )
        self._after_market_engine = AfterMarketEngine(
            adapter=self._adapter,
            executor=self._executor,
            position_mgr=self._position_mgr,
            risk_mgr=self._risk_mgr,
            store=self._store,
            journal=self._journal,
            env=cfg.broker.env,
            dry_run=cfg.strategy.dry_run,
        )

        await self._recover_state()

        # CLOSE_BET 포지션 감지 시 익일 청산 엔진 예약
        if self._position_mgr:
            close_bet_count = sum(
                1 for p in self._position_mgr.active_positions().values()
                if p.position_type == PositionType.CLOSE_BET
            )
            if close_bet_count > 0:
                logger.info(
                    "[Setup] %d CLOSE_BET position(s) detected — next_open_exit_engine will run",
                    close_bet_count,
                )

        logger.info("Preparing ATR cache...")
        await self._scanner.prepare(symbols)

        self._ws_symbols = list(symbols or [])
        await self._start_ws(self._ws_symbols)

        logger.info("Setup complete.")

    async def _teardown(self) -> None:
        if self._status not in (BotStatus.TERMINATED,):
            self._status = BotStatus.STOPPED
            logger.info("[→STOPPED] Teardown.")
        if self._ws_subscriber:
            try:
                self._ws_subscriber.stop()
            except Exception:
                pass
        if self._store:
            await self._store.close()
        logger.info("ScalpingBot teardown complete.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 재시작 복구
    # ═══════════════════════════════════════════════════════════════════════════

    async def _recover_state(self) -> None:
        if not self._store or not self._position_mgr or not self._risk_mgr:
            return
        loop = asyncio.get_event_loop()

        # Step 1: StateStore에서 포지션 복구 (BUG-10/11/12/13 FIX: from_snapshot으로 전체 복원)
        saved_positions: dict = {}
        try:
            saved_positions = await self._store.load_positions()
            for symbol, data in saved_positions.items():
                logger.info("Recovering position from store: %s", symbol)
                pos = self._position_mgr.restore_position(data)
                self._signal_engine.register(symbol)
                logger.info(
                    "Recovered: %s phase=%s qty=%d avg=%.0f stop=%.0f",
                    symbol, pos.phase.value, pos.remaining_qty,
                    pos.avg_price, pos.hard_stop,
                )
        except Exception as exc:
            logger.error("Position recovery failed: %s", exc)
            await self.kill_switch(KillReason.STATE_SYNC_FAIL)
            return

        # Step 2: broker 계좌 sync + broker-only 포지션 복구
        broker_holdings: dict = {}
        broker_query_ok = False
        try:
            bal = await loop.run_in_executor(
                None,
                lambda: self._adapter.inquire_balance(env_dv=self._cfg.broker.env),
            )
            if bal.get("status") == "ok":
                broker_holdings = {
                    h["symbol"]: h for h in (bal.get("holdings") or [])
                    if int(h.get("qty") or 0) > 0
                }
                broker_query_ok = True
        except Exception as exc:
            logger.warning("Broker sync failed during recovery: %s", exc)

        if broker_query_ok:
            # StateStore 포지션 vs broker 수량 검증
            for symbol, pos in list(self._position_mgr.active_positions().items()):
                broker_pos = broker_holdings.get(symbol)
                if not broker_pos:
                    logger.warning("Recovery: %s not in broker — clearing internally", symbol)
                    self._position_mgr.get_position(symbol).phase = PositionPhase.CLOSED
                    await self._store.delete_position(symbol)
                else:
                    broker_qty = int(broker_pos.get("qty") or 0)
                    if broker_qty != pos.remaining_qty:
                        logger.warning(
                            "Recovery qty mismatch %s: local=%d broker=%d — using broker",
                            symbol, pos.remaining_qty, broker_qty,
                        )
                        pos.remaining_qty = broker_qty

            # BUG-15 FIX: broker에만 있는 포지션 (StateStore 소실 케이스) 복구
            # POSITION_TYPE FIX: 복구 시각으로 position_type 추론
            store_syms = set(saved_positions.keys())
            now_dt = datetime.now()
            for sym, broker_pos in broker_holdings.items():
                if sym not in store_syms:
                    broker_qty = int(broker_pos.get("qty") or 0)
                    avg_price = float(
                        broker_pos.get("avg_price")
                        or broker_pos.get("purchase_price")
                        or 0
                    )
                    if broker_qty > 0 and avg_price > 0:
                        inferred_pt, inferred_session, inferred_exit = infer_from_recovery_time(now_dt)
                        logger.warning(
                            "[RECOVERY] Broker-only position %s qty=%d avg=%.0f "
                            "— inferred type=%s (%s)",
                            sym, broker_qty, avg_price,
                            inferred_pt.value, inferred_session,
                        )
                        if inferred_pt == PositionType.CLOSE_BET:
                            logger.warning(
                                "[RECOVERY] %s inferred as CLOSE_BET: position exists before "
                                "market open — will run next_open_exit_engine",
                                sym,
                            )
                        data = {
                            "symbol":                   sym,
                            "avg_price":                avg_price,
                            "entry_price":              avg_price,
                            "remaining_qty":            broker_qty,
                            "total_qty":                broker_qty,
                            "phase":                    PositionPhase.ENTERING.value,
                            "atr_at_entry":             0,
                            "hard_stop":                avg_price * (1.0 - 0.03),
                            "break_even_stop":          0,
                            "trailing_high":            avg_price,
                            "trailing_stop":            avg_price * (1.0 - 0.02),
                            "realized_pnl":             0,
                            "exit_1_triggered":         False,
                            "exit_2_triggered":         False,
                            "market":                   "KOSDAQ",
                            "position_type":            inferred_pt.value,
                            "opened_at":                now_dt.isoformat(),
                            "strategy_id":              inferred_pt.value,
                            "entry_session":            inferred_session,
                            "intended_exit_session":    inferred_exit,
                            "listing_market":           listing_market_from_legacy("KOSDAQ").value,
                            "execution_venue":          ExecutionVenue.UNKNOWN.value,
                            "preferred_venue":          ExecutionVenue.KRX.value,
                            "actual_venue":             ExecutionVenue.UNKNOWN.value,
                            "venue_policy":             VenuePolicy.FALLBACK_KRX.value,
                            "market_session":           MarketSession.KRX_REGULAR.value,
                            "krx_entry_price":          avg_price,
                            "nxt_reference_price":      0,
                            "venue_price_gap_at_entry": 0,
                            "nxt_after_signal":         "",
                            "nxt_pre_signal":           "",
                        }
                        self._position_mgr.restore_position(data)
                        self._signal_engine.register(sym)

        # Step 3: 리스크 상태 복구 + kill_switch 이력 확인
        try:
            risk_data = await self._store.load_risk()
            if risk_data and risk_data.get("kill_switch"):
                logger.critical("Kill switch was active at last shutdown — starting PAUSED")
                self._status = BotStatus.PAUSED
        except Exception as exc:
            logger.warning("Risk state recovery failed: %s", exc)

        logger.info(
            "State recovery complete. positions=%d broker_ok=%s",
            len(self._position_mgr.active_positions()), broker_query_ok,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # WebSocket 연결 + 재연결
    # ═══════════════════════════════════════════════════════════════════════════

    async def _start_ws(self, symbols: list[str]) -> None:
        if not symbols:
            logger.info("No symbols for WebSocket subscription.")
            return

        try:
            from src.brokers.kis_websocket import make_tick_subscriber

            def on_tick_raw(tick_data: Any) -> None:
                try:
                    tick = TickEvent(
                        symbol=tick_data.symbol,
                        price=tick_data.price,
                        buy_vol_total=tick_data.buy_vol_total,
                        sell_vol_total=tick_data.sell_vol_total,
                        bid_qty=tick_data.bid_qty,
                        ask_qty=tick_data.ask_qty,
                        tick_vol=tick_data.tick_vol,
                        acml_vol=getattr(tick_data, "acml_vol", 0.0),
                        acml_tr_pbmn=getattr(tick_data, "acml_tr_pbmn", 0.0),
                        time_str=getattr(tick_data, "time", ""),
                        is_vi=getattr(tick_data, "is_vi", False),
                        ask1_price=getattr(tick_data, "ask1_price", 0.0),
                        bid1_price=getattr(tick_data, "bid1_price", 0.0),
                        ask1_qty=getattr(tick_data, "ask1_qty", 0.0),
                        bid1_qty=getattr(tick_data, "bid1_qty", 0.0),
                        ask2_price=getattr(tick_data, "ask2_price", 0.0),
                        ask2_qty=getattr(tick_data, "ask2_qty", 0.0),
                        bid2_price=getattr(tick_data, "bid2_price", 0.0),
                        bid2_qty=getattr(tick_data, "bid2_qty", 0.0),
                        ask3_price=getattr(tick_data, "ask3_price", 0.0),
                        ask3_qty=getattr(tick_data, "ask3_qty", 0.0),
                        bid3_price=getattr(tick_data, "bid3_price", 0.0),
                        bid3_qty=getattr(tick_data, "bid3_qty", 0.0),
                        ask4_price=getattr(tick_data, "ask4_price", 0.0),
                        ask4_qty=getattr(tick_data, "ask4_qty", 0.0),
                        bid4_price=getattr(tick_data, "bid4_price", 0.0),
                        bid4_qty=getattr(tick_data, "bid4_qty", 0.0),
                        ask5_price=getattr(tick_data, "ask5_price", 0.0),
                        ask5_qty=getattr(tick_data, "ask5_qty", 0.0),
                        bid5_price=getattr(tick_data, "bid5_price", 0.0),
                        bid5_qty=getattr(tick_data, "bid5_qty", 0.0),
                        ask6_price=getattr(tick_data, "ask6_price", 0.0),
                        ask6_qty=getattr(tick_data, "ask6_qty", 0.0),
                        bid6_price=getattr(tick_data, "bid6_price", 0.0),
                        bid6_qty=getattr(tick_data, "bid6_qty", 0.0),
                        ask7_price=getattr(tick_data, "ask7_price", 0.0),
                        ask7_qty=getattr(tick_data, "ask7_qty", 0.0),
                        bid7_price=getattr(tick_data, "bid7_price", 0.0),
                        bid7_qty=getattr(tick_data, "bid7_qty", 0.0),
                        ask8_price=getattr(tick_data, "ask8_price", 0.0),
                        ask8_qty=getattr(tick_data, "ask8_qty", 0.0),
                        bid8_price=getattr(tick_data, "bid8_price", 0.0),
                        bid8_qty=getattr(tick_data, "bid8_qty", 0.0),
                        ask9_price=getattr(tick_data, "ask9_price", 0.0),
                        ask9_qty=getattr(tick_data, "ask9_qty", 0.0),
                        bid9_price=getattr(tick_data, "bid9_price", 0.0),
                        bid9_qty=getattr(tick_data, "bid9_qty", 0.0),
                        ask10_price=getattr(tick_data, "ask10_price", 0.0),
                        ask10_qty=getattr(tick_data, "ask10_qty", 0.0),
                        bid10_price=getattr(tick_data, "bid10_price", 0.0),
                        bid10_qty=getattr(tick_data, "bid10_qty", 0.0),
                        orderbook_source_ts=getattr(tick_data, "orderbook_source_ts", 0.0),
                        orderbook_received_ts=getattr(tick_data, "orderbook_received_ts", 0.0),
                        orderbook_age_sec=getattr(tick_data, "orderbook_age_sec", 999.0),
                        depth_levels_available=getattr(tick_data, "depth_levels_available", 1),
                        orderbook_stale=getattr(tick_data, "orderbook_stale", True),
                        orderbook_quality=getattr(tick_data, "orderbook_quality", "fallback"),
                        invalid_orderbook=getattr(tick_data, "invalid_orderbook", False),
                        orderbook_invalid_reason=getattr(tick_data, "orderbook_invalid_reason", ""),
                    )
                    self.enqueue_tick(tick)
                except Exception as exc:
                    logger.debug("on_tick_raw error: %s", exc)

            # BUG-07 FIX: H0STCNI9 체결통보 → OrderExecutor.on_fill_notify() 연결
            def on_fill_raw(fill_data: Any) -> None:
                try:
                    if self._executor:
                        self._executor.on_fill_notify(
                            fill_data.order_no, fill_data.qty, fill_data.price
                        )
                except Exception as exc:
                    logger.debug("on_fill_raw error: %s", exc)

            env = self._cfg.broker.env
            subscriber = make_tick_subscriber(
                self._adapter, symbols, on_tick_raw,
                on_fill_notify=on_fill_raw,
                env=env,
            )
            subscriber.start_background()
            self._ws_subscriber = subscriber
            self._last_tick_ts = time.monotonic()
            self._ws_reconnect_count = 0
            logger.info("WebSocket subscribed: %d symbols env=%s", len(symbols), env)

        except Exception as exc:
            logger.error("WebSocket start failed: %s", exc)

    async def _reconnect_ws(self, degraded: bool = False) -> None:
        """
        WebSocket 재연결 — exponential backoff.
        degraded=True: STOPPING 중 재연결. execution 채널만 유지.
        """
        self._ws_reconnect_count += 1
        # BUG-19 FIX: STOPPING 중에는 backoff 상한을 STOPPING_WS_BACKOFF_CAP(5s)으로 제한
        max_backoff = STOPPING_WS_BACKOFF_CAP if degraded else 60.0
        backoff = min(5.0 * (2 ** (self._ws_reconnect_count - 1)), max_backoff)
        logger.warning(
            "WebSocket reconnecting... attempt=%d backoff=%.0fs degraded=%s",
            self._ws_reconnect_count, backoff, degraded,
        )
        await asyncio.sleep(backoff)

        if self._ws_subscriber:
            try:
                self._ws_subscriber.stop()
            except Exception:
                pass
            self._ws_subscriber = None

        symbols = self._ws_symbols or list(self._watchlist)

        if degraded:
            # STOPPING 중: market data 최소화, execution 채널만 유지
            # 현재 포지션 보유 종목만 재구독
            active_syms = list(self._position_mgr.active_positions().keys()) if self._position_mgr else []
            if active_syms:
                logger.info(
                    "[STOPPING] Degraded reconnect: subscribing %d active position symbols only",
                    len(active_syms),
                )
                await self._start_ws(active_syms)
            else:
                logger.info("[STOPPING] No active positions — skip WS reconnect")
        else:
            await self._start_ws(symbols)

    # ═══════════════════════════════════════════════════════════════════════════
    # WS Watchdog — 실행 루프 (RUNNING + STOPPING)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _ws_watchdog(self) -> None:
        """
        WebSocket stale tick 감지 → 재연결.
        STOPPING 중에도 유지 (체결 이벤트 수신 필요).
        STOPPING 중에는 degraded 모드로 재연결.
        """
        await asyncio.sleep(10.0)  # 초기 워밍업 대기
        while _is_execution_active(self._status) and not self._kill_event.is_set():
            is_stopping = self._status == BotStatus.STOPPING

            if self._last_tick_ts > 0 and self._status == BotStatus.RUNNING:
                stale_age = time.monotonic() - self._last_tick_ts
                trip_reason = self._live_guard.observe_tick_age(stale_age)
                if trip_reason:
                    logger.critical("[LiveGuard] %s age=%.1fs — kill_switch", trip_reason, stale_age)
                    await self.kill_switch(KillReason.LIVE_GUARD)
                    return

            if (self._ws_subscriber is not None
                    and self._last_tick_ts > 0
                    and time.monotonic() - self._last_tick_ts > self._ws_stale_secs):
                logger.warning(
                    "WebSocket stale (no tick %.0fs) — reconnecting [degraded=%s]",
                    self._ws_stale_secs, is_stopping,
                )
                await self._reconnect_ws(degraded=is_stopping)

            await asyncio.sleep(5.0)

        logger.info("WS watchdog stopped. status=%s", self._status.value)

    def enqueue_tick(self, tick: TickEvent) -> None:
        """H0STCNT0 콜백 → asyncio 큐 (스레드 안전)."""
        self._last_tick_ts = time.monotonic()
        # STOPPING 이후는 큐에 넣지 않음 (전략/청산 루프 종료됨)
        if not _is_active(self._status):
            return
        loop = asyncio.get_event_loop()
        if loop.is_running():
            try:
                loop.call_soon_threadsafe(self._tick_queue.put_nowait, tick)
            except asyncio.QueueFull:
                logger.warning("Tick queue full — dropping tick %s", tick.symbol)

    # ═══════════════════════════════════════════════════════════════════════════
    # 틱 처리 — 전략 루프 (RUNNING only)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _tick_dispatcher(self) -> None:
        # RUNNING + PAUSED: 전략/청산 루프 유지
        # PAUSED 중에는 _process_tick 내부에서 신규 진입만 차단
        while _is_active(self._status) and not self._kill_event.is_set():
            try:
                tick = await asyncio.wait_for(self._tick_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._process_tick(tick)
            except Exception as exc:
                logger.error("_process_tick unhandled: %s — %s", tick.symbol, exc)

        # STOPPING/STOPPED: 큐에 남은 틱 드레인 (무한 증가 방지)
        drained = 0
        while not self._tick_queue.empty():
            try:
                self._tick_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.info("Tick dispatcher stopped. Drained %d queued ticks.", drained)
        else:
            logger.info("Tick dispatcher stopped.")

    def _observe_tick_microstructure(self, tick: TickEvent) -> None:
        """KRX 실시간 틱을 시초 캔들/호가 품질 엔진에 공급한다.

        NXT WebSocket은 별도 venue 이벤트가 붙으면 같은 엔진의 on_quote/on_trade를
        직접 호출하면 된다. 지금은 기존 KRX H0STCNT0 틱을 손상 없이 재사용한다.
        """
        venue = ExecutionVenue.KRX
        ts = tick.ts or datetime.now()
        if tick.bid1_price > 0 or tick.ask1_price > 0:
            self._microstructure_engine.on_quote(
                QuoteEvent(
                    symbol=tick.symbol,
                    venue=venue,
                    bid1=tick.bid1_price,
                    ask1=tick.ask1_price,
                    bid_size1=tick.bid1_qty or tick.bid_qty,
                    ask_size1=tick.ask1_qty or tick.ask_qty,
                    ts=ts,
                )
            )
        if tick.tick_vol > 0 and tick.price > 0:
            side = "buy" if tick.buy_vol_total >= tick.sell_vol_total else "sell"
            trade = TradePrint(
                symbol=tick.symbol,
                venue=venue,
                price=tick.price,
                qty=int(tick.tick_vol),
                side=side,
                ts=ts,
            )
            self._microstructure_engine.on_trade(trade)
            self._opening_candle_engine.on_trade(trade)

    def _record_orderbook_tick_diagnostics(self, tick: TickEvent) -> None:
        if not self._strategy_journal:
            return
        spread_pct = 0.0
        if tick.price > 0 and tick.ask1_price > 0 and tick.bid1_price > 0:
            spread_pct = max(0.0, (tick.ask1_price - tick.bid1_price) / tick.price)
        quality = getattr(tick, "orderbook_quality", "fallback")
        depth = int(getattr(tick, "depth_levels_available", 1) or 1)
        age = float(getattr(tick, "orderbook_age_sec", 999.0) or 999.0)
        self._strategy_journal.record_order_event("tick_merge_result", {
            "symbol": tick.symbol,
            "tick_received_ts": tick.ts.timestamp() if tick.ts else 0.0,
            "orderbook_received_ts": getattr(tick, "orderbook_received_ts", 0.0),
            "orderbook_age_sec": age,
            "merged": depth >= 2 and not getattr(tick, "orderbook_stale", True),
            "fallback_mode": depth < 3 or getattr(tick, "orderbook_stale", True),
            "depth_levels_available": depth,
            "orderbook_quality": quality,
        })
        self._strategy_journal.record_order_event("orderbook_snapshot", {
            "symbol": tick.symbol,
            "depth_levels_available": depth,
            "orderbook_age_sec": age,
            "spread_pct": spread_pct,
            "bid1": tick.bid1_price,
            "ask1": tick.ask1_price,
            "bid1_qty": tick.bid1_qty or tick.bid_qty,
            "ask1_qty": tick.ask1_qty or tick.ask_qty,
            "best_depth_qty": min(tick.bid1_qty or tick.bid_qty, tick.ask1_qty or tick.ask_qty),
            "orderbook_quality": quality,
            "invalid_reason": getattr(tick, "orderbook_invalid_reason", ""),
        })

    def _record_candidate_provenance(self, candidates: list[Any]) -> None:
        for c in candidates[:50]:
            sources = list(getattr(c, "candidate_sources", []) or getattr(c, "sources", []) or [])
            if not sources:
                sources = []
                if getattr(c, "leader_rank", 999) <= 3:
                    sources.append("LEADER_ROTATION")
                if float(getattr(c, "vol_ratio", 0.0) or 0.0) >= 2.0:
                    sources.append("VOLUME_SPIKE")
                if float(getattr(c, "trading_value", 0.0) or 0.0) > 0:
                    sources.append("VALUE_TOP")
                if bool(getattr(c, "is_vi", False)):
                    sources.append("VI_TRIGGERED")
            primary = str(sources[0]) if sources else "SCAN"
            score = (
                len(sources) * 10.0
                + max(0.0, 100.0 - float(getattr(c, "leader_rank", 999) or 999))
                + min(30.0, float(getattr(c, "vol_ratio", 0.0) or 0.0) * 5.0)
            )
            self._strategy_journal.record_order_event("candidate_provenance_snapshot", {
                "symbol": getattr(c, "symbol", ""),
                "name": getattr(c, "name", ""),
                "candidate_sources": sources,
                "source_count": len(sources),
                "primary_source": primary,
                "provenance_score": round(score, 2),
                "leader_rank": getattr(c, "leader_rank", 999),
                "leader_score": getattr(c, "leader_score", 0.0),
                "vol_ratio": getattr(c, "vol_ratio", 0.0),
                "trading_value": getattr(c, "trading_value", 0.0),
            })

    async def _process_tick(self, tick: TickEvent) -> None:
        if not self._signal_engine or not self._position_mgr or not self._risk_mgr:
            return

        # 전략 루프가 살아있는 상태에서만 처리 (RUNNING + PAUSED)
        if not _is_active(self._status):
            return

        self._observe_tick_microstructure(tick)
        self._record_orderbook_tick_diagnostics(tick)
        if self._executor:
            self._executor.update_market_snapshot(tick)
        self._update_execution_quality(tick)

        if tick.is_vi:
            self._risk_mgr.set_vi_cooldown(tick.symbol)
            self._regime_analyzer.record_vi()

        market_ok = (self._scanner.kosdaq_change_pct > -0.015
                     if self._scanner else True)
        sig = self._signal_engine.process_tick(
            tick, market_strength=1.0 if market_ok else 0.3
        )
        signal_snapshot = self._signal_engine.get_signal_snapshot(tick.symbol)
        self._record_signal_snapshot(tick.symbol, signal_snapshot)
        self._shadow_engine.on_tick(tick, signal_snapshot=signal_snapshot)
        routed_signals = self._strategy_router.route_tick(
            tick,
            self._signal_engine.get_symbol_state(tick.symbol),
            StrategyContext(
                now_time=datetime.now().time(),
                regime=self._current_runtime_regime().regime.value,
                market_ok=market_ok,
                candidate=self._candidate_cache.get(tick.symbol),
                signal_snapshot=signal_snapshot,
                symbol_state=self._signal_engine.get_symbol_state(tick.symbol),
            ),
        )
        for routed in routed_signals:
            mode = "live" if routed.live_allowed and not routed.shadow_only else "shadow"
            self._strategy_journal.record_signal(routed, mode=mode)
            self._shadow_engine.observe_strategy_signal(routed)
            if mode == "shadow":
                self._shadow_entry_counts[routed.strategy_name] = (
                    self._shadow_entry_counts.get(routed.strategy_name, 0) + 1
                )
            self._last_strategy_signal_counts[routed.strategy_name] = (
                self._last_strategy_signal_counts.get(routed.strategy_name, 0) + 1
            )
            if routed.entry_price is None:
                candidate = self._candidate_cache.get(routed.symbol)
                self._strategy_journal.record_reject(
                    symbol=routed.symbol,
                    name=getattr(candidate, "name", "") if candidate else "",
                    strategy=routed.strategy_name,
                    stage="signal",
                    reject_reason=routed.reason,
                    metrics=routed.metrics,
                    market_regime=self._regime_analyzer.current_regime.value,
                    schedule=self._current_schedule_name(),
                    tick_age_sec=signal_snapshot.get("last_tick_age_sec"),
                    feature_readiness=self._feature_readiness(signal_snapshot),
                )
                if candidate:
                    self._shadow_engine.observe_rejected_candidate(
                        candidate,
                        strategy=routed.strategy_name,
                        reject_reason=routed.reason,
                        metrics={
                            **routed.metrics,
                            "expected_entry_price": routed.entry_price or tick.price,
                            "bid1_price": tick.bid1_price,
                            "ask1_price": tick.ask1_price,
                        },
                    )
        live_strategy_signal = self._select_live_strategy_signal(routed_signals)
        if live_strategy_signal:
            promotion_key = (
                "leader_only_shallow_pullback"
                if live_strategy_signal.strategy_name == "shallow_pullback"
                else live_strategy_signal.strategy_name
            )
            record_id = self._strategy_journal.record_id_for(live_strategy_signal.symbol, promotion_key)
            promotion_state = self._promotion_gate.state_for(promotion_key)
            if promotion_state in {
                PromotionState.DRY_RUN_LIVE,
                PromotionState.SMALL_LIVE,
                PromotionState.NORMAL_LIVE,
            }:
                runtime = self._runtime_permission_gate.evaluate(
                    strategy=promotion_key,
                    promotion_state=promotion_state,
                    regime=self._current_runtime_regime(),
                    execution_quality=self._current_execution_quality(),
                    market_phase=str(self._strategy_schedule_snapshot().get("market_phase", "")).upper(),
                    last_tick_age_sec=signal_snapshot.get("last_tick_age_sec"),
                    stale_feature_age_sec=signal_snapshot.get("last_tick_age_sec"),
                    metrics=live_strategy_signal.metrics,
                )
                self._record_runtime_permission(runtime)
                self._record_gatekeeper_snapshot(
                    record_id=record_id,
                    symbol=live_strategy_signal.symbol,
                    strategy=promotion_key,
                    final_decision="allow" if runtime.allowed else "block",
                    signal_score=live_strategy_signal.confidence * 100.0,
                    leader_score=float(live_strategy_signal.metrics.get("leader_score", 0.0) or 0.0),
                    promotion_state=promotion_state.value,
                    runtime_permission=runtime.runtime_permission,
                    terminal_blocker=runtime.blocked_reason,
                    blocker_reason=runtime.blocked_reason,
                    feature_snapshot={**signal_snapshot, **live_strategy_signal.metrics},
                )
                if runtime.allowed:
                    sig = self._strategy_signal_to_event(live_strategy_signal, tick)
                else:
                    self._strategy_journal.record_reject(
                        symbol=live_strategy_signal.symbol,
                        name=getattr(self._candidate_cache.get(live_strategy_signal.symbol), "name", ""),
                        strategy=promotion_key,
                        stage="order",
                        reject_reason=runtime.blocked_reason,
                        metrics={
                            **live_strategy_signal.metrics,
                            "promotion_state": promotion_state.value,
                            "runtime_permission": runtime.runtime_permission,
                            "regime_score": self._current_runtime_regime().score,
                            "execution_quality_score": self._current_execution_quality().score,
                            "expected_entry_price": live_strategy_signal.entry_price,
                        },
                        market_regime=self._current_runtime_regime().regime.value,
                        schedule=self._current_schedule_name(),
                        tick_age_sec=signal_snapshot.get("last_tick_age_sec"),
                        feature_readiness=self._feature_readiness(signal_snapshot),
                    )
            else:
                self._record_gatekeeper_snapshot(
                    record_id=record_id,
                    symbol=live_strategy_signal.symbol,
                    strategy=promotion_key,
                    final_decision="shadow_only",
                    signal_score=live_strategy_signal.confidence * 100.0,
                    leader_score=float(live_strategy_signal.metrics.get("leader_score", 0.0) or 0.0),
                    promotion_state=promotion_state.value,
                    runtime_permission="blocked",
                    terminal_blocker="promotion_gate_shadow_only",
                    blocker_reason="promotion_gate_shadow_only",
                    feature_snapshot={**signal_snapshot, **live_strategy_signal.metrics},
                )
                self._strategy_journal.record_reject(
                    symbol=live_strategy_signal.symbol,
                    name=getattr(self._candidate_cache.get(live_strategy_signal.symbol), "name", ""),
                    strategy=promotion_key,
                    stage="order",
                    reject_reason="promotion_gate_shadow_only",
                    metrics={
                        **live_strategy_signal.metrics,
                        "promotion_state": promotion_state.value,
                        "source_strategy": live_strategy_signal.strategy_name,
                        "expected_entry_price": live_strategy_signal.entry_price,
                    },
                    market_regime=self._current_runtime_regime().regime.value,
                    schedule=self._current_schedule_name(),
                    tick_age_sec=signal_snapshot.get("last_tick_age_sec"),
                    feature_readiness=self._feature_readiness(signal_snapshot),
                )

        now_time = datetime.now().time()
        exit_req = self._position_mgr.check_exits(
            tick.symbol, tick,
            exec_strength=self._signal_engine.get_exec_strength(tick.symbol),
            ob_imbalance=self._signal_engine.get_ob_imbalance(tick.symbol),
            vwap=self._signal_engine.get_vwap(tick.symbol),
            now_time=now_time,
        )
        if exit_req:
            # BUG-16/40 FIX: 청산을 별도 태스크로 디스패치 — tick 루프 블로킹 방지
            asyncio.create_task(
                self._execute_exit(exit_req, expected_price=tick.price, bid1_price=tick.bid1_price)
            )
            return

        total_unreal = sum(
            self._position_mgr.unrealized_pnl(s, tick.price)
            for s in self._position_mgr.active_positions()
        )
        self._risk_mgr.update_unrealized(total_unreal)

        if self._risk_mgr.is_halted:
            await self.kill_switch(KillReason.DAILY_LOSS)
            return

        if (sig and sig.action in ("enter_now", "enter_watch")
                and NO_ENTRY_UNTIL <= now_time < NO_NEW_ENTRY_TIME
                and self._status == BotStatus.RUNNING):
            # 서킷브레이커 발동 중 — 신규 진입 차단 (BUG-37 FIX)
            if self._market_halted:
                self._record_entry_reject(symbol=tick.symbol, strategy="current_strategy", reason="market_halted", stage="order", sig=sig, tick=tick)
                return

            # NO_TRADE 레짐에서는 신규 진입 완전 차단
            policy = self._regime_analyzer.current_policy
            if policy.regime == MarketRegime.NO_TRADE:
                self._record_entry_reject(symbol=tick.symbol, strategy="current_strategy", reason="regime_no_trade", stage="order", sig=sig, tick=tick)
                return

            # 레짐 정책 + 적응형 점수 중 더 높은 기준 적용.
            # 대장주 얕은 눌림은 별도 live-entry 경로라 기존 deep breakout 정책보다 낮은
            # threshold를 허용하되, RiskManager의 adaptive penalty는 유지한다.
            if str(sig.reason).startswith("leader_shallow_pullback"):
                min_score = max(self._risk_mgr.adaptive_min_score(), SHALLOW_ENTRY_SCORE)
            else:
                min_score = max(self._risk_mgr.adaptive_min_score(), policy.min_entry_score)
            # 09:05~09:10 보수 모드: 점수 기준 추가 상향
            if now_time < CONSERVATIVE_ENTRY_UNTIL:
                min_score += CONSERVATIVE_SCORE_BOOST
            if sig.score >= min_score:
                self._shadow_engine.mark_real_signal(sig.symbol)
                await self._handle_entry_signal(sig, tick)
            else:
                self._record_entry_reject(symbol=tick.symbol, strategy="current_strategy", reason="score_below", stage="signal", sig=sig, tick=tick)

    def _record_signal_snapshot(self, symbol: str, snapshot: dict) -> None:
        self._freshness_samples += 1
        if float(snapshot.get("last_tick_age_sec") or 0.0) > 30.0:
            self._stale_feature_samples += 1
        candidate = self._candidate_cache.get(symbol)
        self._strategy_journal.record_signal_snapshot(
            symbol=symbol,
            name=getattr(candidate, "name", "") if candidate else "",
            snapshot=snapshot,
            tick_count=int(snapshot.get("tick_count") or 0),
            last_tick_age_sec=snapshot.get("last_tick_age_sec"),
            stale_feature_age_sec=snapshot.get("last_tick_age_sec"),
            market_regime=self._regime_analyzer.current_regime.value,
            schedule=self._current_schedule_name(),
        )

    @staticmethod
    def _feature_readiness(snapshot: dict) -> dict:
        return {
            "vwap_ready": bool(snapshot.get("vwap_ready")),
            "atr_ready": bool(snapshot.get("atr_ready")),
            "exec_strength_samples": int(snapshot.get("exec_strength_samples") or 0),
            "tick_count": int(snapshot.get("tick_count") or 0),
        }

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _load_historical_strategy_stats(lookback_days: int = 5) -> dict[str, dict]:
        """어제~최근 N일 strategy_reports에서 shadow/live 성과를 로드해 expected edge 캘리브레이션에 사용.

        avg_mfe_pct, avg_mae_pct, net_expectancy, win_rate를 최신 유효 데이터로 반환.
        """
        from datetime import date, timedelta
        stats: dict[str, dict] = {}
        for i in range(1, lookback_days + 1):
            d = (date.today() - timedelta(days=i)).isoformat()
            path = Path("data/strategy_reports") / f"{d}.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                for strategy, s in (payload.get("strategy_stats") or {}).items():
                    if strategy not in stats and int(s.get("sample_count") or 0) >= 10:
                        stats[strategy] = s
            except Exception:
                continue
            if stats:
                break
        return stats

    def _current_runtime_regime(self) -> RegimeSnapshot:
        if self._runtime_regime_snapshot:
            return self._runtime_regime_snapshot
        return self._regime_score_engine.update(RegimeInputs(confirming=True))

    def _current_execution_quality(self) -> ExecutionQualitySnapshot:
        if self._execution_quality_snapshot:
            return self._execution_quality_snapshot
        self._execution_quality_snapshot = self._execution_quality_gate.score(ExecutionQualityInputs())
        return self._execution_quality_snapshot

    def _execution_quality_inputs(self, tick: TickEvent | None = None) -> ExecutionQualityInputs:
        state = self._live_guard.state
        total_order_health = max(1, state.order_timeouts + state.missing_fills + self._live_fill_count + self._live_order_attempt_count)
        stale_tick_ratio = min(1.0, state.stale_tick_repeats / max(1, self._live_guard.config.stale_tick_repeats))
        stale_feature_ratio = (
            self._stale_feature_samples / self._freshness_samples
            if self._freshness_samples else 0.0
        )
        spread_widening_ratio = 0.0
        quote_gap_ratio = 0.0
        if tick and tick.price > 0 and tick.ask1_price > 0 and tick.bid1_price > 0:
            spread_pct = max(0.0, (tick.ask1_price - tick.bid1_price) / tick.price)
            spread_widening_ratio = min(1.0, spread_pct / MAX_ENTRY_SPREAD_PCT)
            quote_gap_ratio = 1.0 if spread_pct > MAX_ENTRY_SPREAD_PCT else 0.0
        orderbook_collapse_ratio = 0.0
        quote_age_ms = 0.0
        tick_age_ms = 0.0
        orderbook_age_sec = 0.0
        top_of_book_missing = False
        depth_levels_available = 1
        if tick:
            qh = self._quote_health_from_tick(tick)
            quote_age_ms = qh.quote_age_ms
            tick_age_ms = qh.tick_age_ms
            orderbook_age_sec = qh.orderbook_age_sec
            top_of_book_missing = qh.top_of_book_missing
            depth_levels_available = qh.depth_levels_available
            if getattr(tick, "invalid_orderbook", False) or getattr(tick, "orderbook_stale", False):
                orderbook_collapse_ratio = 1.0
            elif int(getattr(tick, "depth_levels_available", 1) or 1) < 3:
                orderbook_collapse_ratio = 0.35
        return ExecutionQualityInputs(
            slippage_pct=(
                self._live_guard.config.slippage_limit_pct
                if state.slippage_exceeds else 0.0
            ),
            partial_fill_rate=0.0,
            timeout_rate=min(1.0, state.order_timeouts / total_order_health),
            stale_tick_ratio=stale_tick_ratio,
            stale_feature_ratio=stale_feature_ratio,
            spread_widening_ratio=spread_widening_ratio,
            orderbook_collapse_ratio=orderbook_collapse_ratio,
            quote_gap_ratio=quote_gap_ratio,
            aggressive_sell_spike=0.0,
            api_latency_ms=0.0,
            fill_probability=1.0 - min(1.0, state.order_timeouts / total_order_health),
            quote_age_ms=quote_age_ms,
            websocket_gap_ms=tick_age_ms,
            top_of_book_missing=top_of_book_missing,
            depth_levels_available=depth_levels_available,
        )

    def _update_execution_quality(self, tick: TickEvent | None = None, *, emit: bool = False) -> ExecutionQualitySnapshot:
        if tick:
            self._quote_health_snapshot = self._quote_health_from_tick(tick)
            self._strategy_journal.record_order_event(
                "quote_health_snapshot",
                {
                    "symbol": tick.symbol,
                    **self._quote_health_snapshot.to_dict(),
                },
            )
            self._strategy_journal.record_order_event(
                "latency_state",
                {
                    "symbol": tick.symbol,
                    **self._quote_health_snapshot.to_dict(),
                },
            )
        self._execution_quality_snapshot = self._execution_quality_gate.score(
            self._execution_quality_inputs(tick)
        )
        if emit:
            self._strategy_journal.record_order_event(
                "execution_quality",
                self._execution_quality_snapshot.to_dict(),
            )
        return self._execution_quality_snapshot

    def _quote_health_from_tick(self, tick: TickEvent) -> QuoteHealthSnapshot:
        now = time.time()
        tick_ts = tick.ts.timestamp() if getattr(tick, "ts", None) else now
        tick_age_ms = max(0.0, (now - tick_ts) * 1000.0)
        orderbook_age_sec = float(getattr(tick, "orderbook_age_sec", 999.0) or 999.0)
        quote_age_ms = orderbook_age_sec * 1000.0 if orderbook_age_sec < 900 else tick_age_ms
        spread_pct = 0.0
        if tick.price > 0 and tick.ask1_price > 0 and tick.bid1_price > 0:
            spread_pct = max(0.0, (tick.ask1_price - tick.bid1_price) / tick.price)
        top_missing = tick.bid1_price <= 0 or tick.ask1_price <= 0
        return self._quote_health_monitor.classify(
            quote_age_ms=quote_age_ms,
            tick_age_ms=tick_age_ms,
            orderbook_age_sec=orderbook_age_sec,
            websocket_gap_ms=tick_age_ms,
            spread_pct=spread_pct,
            top_of_book_missing=top_missing,
            depth_levels_available=int(getattr(tick, "depth_levels_available", 1) or 1),
        )

    def _build_regime_inputs(self, candidates: list[Any]) -> RegimeInputs:
        eq = self._current_execution_quality()
        old_score = self._regime_analyzer.last_score
        kosdaq_change = self._scanner.kosdaq_change_pct if self._scanner else 0.0
        index_trend = self._clamp01((kosdaq_change + 0.015) / 0.04)
        ranked = [c for c in candidates if getattr(c, "leader_rank", 999) <= 3]
        leader_scores = [float(getattr(c, "leader_score", 0.0) or 0.0) for c in ranked]
        top_leader_persistence = self._clamp01((sum(leader_scores) / len(leader_scores)) / 100.0) if leader_scores else 0.3
        avg_change = sum(float(getattr(c, "change_pct", 0.0) or 0.0) for c in candidates[:10]) / max(1, min(10, len(candidates)))
        follow_through = self._clamp01(avg_change / 0.08)
        avg_vol_ratio = sum(float(getattr(c, "vol_ratio", 0.0) or 0.0) for c in candidates[:10]) / max(1, min(10, len(candidates)))
        liquidity_concentration = self._clamp01(avg_vol_ratio / 5.0)
        fake_ratio = float(self._regime_analyzer.fake_breakout_ratio or 0.0)
        breakout_success = 1.0 - fake_ratio if fake_ratio > 0 else 0.5
        stale_tick_ratio = (
            self._live_guard.state.stale_tick_repeats
            / max(1, self._live_guard.config.stale_tick_repeats)
        )
        # exec_strength으로 aggressive buy/sell ratio 계산 (100 = 50/50, >100 = buy-heavy)
        exec_strengths: list[float] = []
        vwap_above: list[bool] = []
        if self._signal_engine:
            for cand in candidates[:10]:
                sym = getattr(cand, "symbol", "") or getattr(cand, "metrics", {}).get("symbol", "")
                if sym:
                    es = self._signal_engine.get_exec_strength(sym)
                    exec_strengths.append(min(200.0, max(0.0, float(es or 100.0))))
                    snap = self._signal_engine.get_signal_snapshot(sym)
                    if snap.get("vwap") and snap.get("price"):
                        vwap_above.append(float(snap["price"]) >= float(snap["vwap"]))
        avg_es = sum(exec_strengths) / len(exec_strengths) if exec_strengths else 100.0
        aggressive_buy_ratio = self._clamp01(avg_es / 200.0)
        aggressive_sell_ratio = 1.0 - aggressive_buy_ratio
        vwap_hold_ratio = sum(vwap_above) / len(vwap_above) if vwap_above else 0.5
        return RegimeInputs(
            index_trend=index_trend,
            top_leader_persistence=top_leader_persistence,
            vwap_hold_ratio=vwap_hold_ratio,
            follow_through_ratio=follow_through,
            breakout_success_ratio=breakout_success,
            fake_breakout_ratio=fake_ratio,
            spread_stability=1.0 - self._clamp01((old_score.spread_avg if old_score else 0.0) / MAX_ENTRY_SPREAD_PCT),
            vi_density=self._clamp01((old_score.vi_count_30m if old_score else 0) / 10.0),
            stale_tick_ratio=stale_tick_ratio,
            execution_quality_score=eq.score,
            orderbook_stability=0.5,
            aggressive_buy_ratio=aggressive_buy_ratio,
            aggressive_sell_ratio=aggressive_sell_ratio,
            leader_rotation_speed=1.0 - top_leader_persistence,
            liquidity_concentration=liquidity_concentration,
            upper_tail_ratio=0.5,
            failed_breakout_speed=fake_ratio,
            confirming=self._regime_analyzer.current_regime == MarketRegime.NO_TRADE and len(candidates) == 0,
        )

    def _update_runtime_regime(self, candidates: list[Any]) -> RegimeSnapshot:
        snapshot = self._regime_score_engine.update(self._build_regime_inputs(candidates))
        self._runtime_regime_snapshot = snapshot
        self._strategy_journal.record_order_event("regime_snapshot", snapshot.to_dict())
        if snapshot.hard_shift_triggered:
            self._emit_alert(
                kind="hard_regime_shift",
                severity="warning",
                message=f"hard regime shift: {snapshot.regime_shift_reason}",
                payload=snapshot.to_dict(),
            )
        return snapshot

    def _emit_alert(self, *, kind: str, severity: str, message: str, payload: dict | None = None) -> None:
        try:
            self._alert_sink.emit(AlertEvent(kind=kind, severity=severity, message=message, payload=payload or {}))
        except Exception as exc:
            logger.warning("alert emit failed kind=%s: %s", kind, exc)

    def _record_runtime_permission(self, decision: Any) -> None:
        data = decision.to_dict()
        self._last_runtime_permission[decision.strategy] = data
        self._strategy_journal.record_order_event("runtime_permission", data)
        state = (decision.runtime_permission, decision.blocked_reason)
        if self._last_alerted_runtime_permission.get(decision.strategy) != state:
            self._last_alerted_runtime_permission[decision.strategy] = state
            if decision.blocked_reason:
                self._emit_alert(
                    kind="runtime_permission_changed",
                    severity="warning",
                    message=f"{decision.strategy} {decision.runtime_permission}: {decision.blocked_reason}",
                    payload=data,
                )

    def _record_gatekeeper_snapshot(
        self,
        *,
        record_id: str,
        symbol: str,
        strategy: str,
        final_decision: str,
        signal_score: float = 0.0,
        leader_score: float = 0.0,
        promotion_state: str = "",
        runtime_permission: str = "",
        terminal_blocker: str = "",
        blocker_reason: str = "",
        feature_snapshot: dict[str, Any] | None = None,
    ) -> None:
        regime = self._current_runtime_regime()
        qh = self._quote_health_snapshot
        eq = self._current_execution_quality()
        snapshot = GatekeeperSnapshot(
            record_id=record_id,
            symbol=symbol,
            strategy=strategy,
            signal_score=signal_score,
            leader_score=leader_score,
            regime_score=regime.score,
            promotion_state=promotion_state,
            runtime_permission=runtime_permission,
            quote_health_state=qh.latency_state.value if qh else "",
            latency_state=qh.latency_state.value if qh else "",
            execution_quality_score=eq.score,
            risk_state="",
            final_decision=final_decision,
            terminal_blocker=terminal_blocker,
            blocker_reason=blocker_reason,
            full_feature_snapshot=feature_snapshot or {},
        )
        row = self._gatekeeper_replay.append(snapshot)
        self._strategy_journal.record_order_event("gatekeeper_snapshot", row)

    def _current_schedule_name(self) -> str:
        try:
            return str(self._strategy_schedule_snapshot()["current"])
        except Exception:
            return ""

    def _record_entry_reject(
        self,
        *,
        symbol: str,
        strategy: str,
        reason: str,
        stage: str,
        sig: Any = None,
        tick: TickEvent | None = None,
        extra_metrics: dict[str, Any] | None = None,
    ) -> None:
        candidate = self._candidate_cache.get(symbol)
        snapshot = self._signal_engine.get_signal_snapshot(symbol) if self._signal_engine else {}
        metrics = {
            "score": getattr(sig, "score", 0.0),
            "reason": getattr(sig, "reason", ""),
            "price": tick.price if tick else 0.0,
            **snapshot,
        }
        if extra_metrics:
            metrics.update(extra_metrics)
        self._reject_reason_counter[reason] += 1
        self._strategy_journal.record_reject(
            symbol=symbol,
            name=getattr(candidate, "name", "") if candidate else "",
            strategy=strategy,
            stage=stage,
            reject_reason=reason,
            metrics=metrics,
            market_regime=self._regime_analyzer.current_regime.value,
            schedule=self._current_schedule_name(),
            tick_age_sec=snapshot.get("last_tick_age_sec"),
            feature_readiness=self._feature_readiness(snapshot),
        )
        if candidate:
            self._shadow_engine.observe_rejected_candidate(
                candidate,
                strategy=strategy,
                reject_reason=reason,
                metrics=metrics,
            )

    def _evaluate_microprice_entry_gate(
        self,
        *,
        symbol: str,
        strategy: str,
        tick: TickEvent,
        qty: int,
        snapshot: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        """Final executable-liquidity check before a live entry order."""
        gated_strategies = {
            "leader_only_shallow_pullback",
            "shallow_pullback",
            "vwap_reclaim",
            "momentum_continuation",
        }
        if strategy not in gated_strategies:
            return True, "", {}

        book_age = float(getattr(tick, "orderbook_age_sec", 999.0) or 999.0)
        if getattr(tick, "invalid_orderbook", False):
            metrics = {
                "orderbook_age_sec": book_age,
                "depth_levels_available": getattr(tick, "depth_levels_available", 0),
                "orderbook_quality": getattr(tick, "orderbook_quality", "invalid"),
                "orderbook_invalid_reason": getattr(tick, "orderbook_invalid_reason", "invalid_orderbook"),
            }
            return False, "invalid_orderbook", metrics

        book = snapshot_from_tick(tick, tick_age_sec=book_age)
        pressure = self._orderbook_filter.evaluate(book, required_qty=max(1, qty))
        stability = self._orderbook_stability_observer.observe(book)
        limit_price = tick.ask1_price if tick.ask1_price > 0 else tick.price
        depth = self._depth_fill_simulator.simulate(
            book,
            side="buy",
            qty=max(1, qty),
            limit_price=limit_price,
        )
        pressure_data = pressure.to_dict()
        depth_data = depth.to_dict()
        self._strategy_journal.record_order_event("microprice_snapshot", {
            "symbol": symbol,
            "strategy": strategy,
            "orderbook_age_sec": book_age,
            "depth_levels_available": getattr(tick, "depth_levels_available", 1),
            "orderbook_quality": getattr(tick, "orderbook_quality", "fallback"),
            **pressure_data,
        })
        self._strategy_journal.record_order_event("depth_fill_estimate", {
            "symbol": symbol,
            "strategy": strategy,
            "limit_price": limit_price,
            "orderbook_age_sec": book_age,
            "depth_levels_available": getattr(tick, "depth_levels_available", 1),
            "fallback_mode": getattr(tick, "depth_levels_available", 1) < 3,
            **depth_data,
        })
        self._strategy_journal.record_order_event("orderbook_stability_snapshot", {
            "strategy": strategy,
            **stability.to_dict(),
        })

        metrics = {
            "orderbook_pressure": pressure_data,
            "depth_fill": depth_data,
            "orderbook_stability": stability.to_dict(),
            "orderbook_age_sec": book_age,
            "depth_levels_available": getattr(tick, "depth_levels_available", 1),
            "orderbook_quality": getattr(tick, "orderbook_quality", "fallback"),
        }
        if pressure.blocked:
            return False, pressure.block_reason or "microprice_filter_blocked", metrics
        if depth.filled_qty <= 0:
            return False, depth.reason or "depth_fill_unavailable", metrics
        if depth.partial_fill and depth.filled_qty < max(1, int(qty * 0.5)):
            return False, "depth_partial_too_small", metrics
        if depth.expected_slippage_pct > 0.003:
            return False, "depth_slippage_too_high", metrics
        return True, "", metrics

    def _evaluate_expected_edge_gate(
        self,
        *,
        symbol: str,
        strategy: str,
        sig: Any,
        tick: TickEvent,
        snapshot: dict[str, Any],
        runtime: Any,
        micro_metrics: dict[str, Any],
    ):
        pressure = micro_metrics.get("orderbook_pressure") or {}
        depth = micro_metrics.get("depth_fill") or {}
        stability = micro_metrics.get("orderbook_stability") or {}
        spread_pct = 0.0
        if tick.price > 0 and tick.ask1_price > 0 and tick.bid1_price > 0:
            spread_pct = max(0.0, (tick.ask1_price - tick.bid1_price) / tick.price)
        regime = self._current_runtime_regime()
        eq = self._current_execution_quality()
        execution_state = "DANGER" if eq.blocked else (
            self._quote_health_snapshot.latency_state.value if self._quote_health_snapshot else "SAFE"
        )
        hist = self._historical_strategy_stats.get(strategy) or {}
        hist_mfe = float(hist.get("avg_mfe_pct") or 0.0)
        hist_mae = float(hist.get("avg_mae_pct") or 0.0)
        hist_net = float(hist.get("net_expectancy") or 0.0)
        hist_hit_rate = float(hist.get("win_rate") or 0.0)
        inputs = ExpectedEdgeInputs(
            strategy_name=strategy,
            regime_score=regime.score,
            current_regime=regime.regime.value,
            breakout_success_ratio=float((regime.components or {}).get("breakout_success_ratio", 0.5) or 0.5),
            fake_breakout_ratio=1.0 - float((regime.components or {}).get("fake_breakout_quality", 0.5) or 0.5),
            leader_persistence_score=float((regime.components or {}).get("top_leader_persistence", 0.5) or 0.5),
            strategy_promotion_state=runtime.promotion_state,
            strategy_net_expectancy=hist_net if hist_net != 0.0 else float(getattr(sig, "expected_edge_pct", 0.0) or 0.0),
            historical_strategy_mfe_avg=hist_mfe,
            historical_strategy_mae_avg=hist_mae,
            strategy_hit_rate=hist_hit_rate,
            leader_score=float(snapshot.get("leader_score") or 0.0),
            rank=int(snapshot.get("leader_rank") or snapshot.get("rank") or 999),
            vwap_gap=float(snapshot.get("vwap_gap") or getattr(sig, "vwap_gap", 0.0) or 0.0),
            pullback_depth=float(snapshot.get("pullback_pct") or 0.0),
            recovery_strength=float(snapshot.get("exec_strength") or getattr(sig, "exec_strength", 0.0) or 0.0),
            spread_pct=spread_pct,
            expected_slippage_pct=float(depth.get("expected_slippage_pct") or 0.0),
            orderbook_age_sec=float(getattr(tick, "orderbook_age_sec", 999.0) or 999.0),
            depth_levels_available=int(getattr(tick, "depth_levels_available", 1) or 1),
            microprice_edge=float(pressure.get("microprice_vs_mid") or stability.get("microprice_edge") or 0.0),
            orderbook_pressure=float(pressure.get("weighted_book_pressure") or 0.5),
            fill_probability=1.0 if not depth.get("partial_fill") else 0.5,
            partial_fill_penalty=float(depth.get("cancel_replace_cost_pct") or 0.0),
            daily_pnl=float(self._risk_mgr.state.realized_pnl if self._risk_mgr else 0.0),
            consecutive_losses=int(self._risk_mgr.state.consecutive_losses if self._risk_mgr else 0),
            max_daily_trades_remaining=max(0, int(runtime.max_daily_trades or 0)),
            current_position_count=len(self._position_mgr.active_positions()) if self._position_mgr else 0,
            execution_quality_state=execution_state,
        )
        decision = self._expected_edge_model.evaluate(inputs)
        payload = {
            "symbol": symbol,
            "strategy": strategy,
            **decision.to_dict(),
        }
        self._strategy_journal.record_order_event("expected_edge_snapshot", payload)
        self._strategy_journal.record_order_event("exit_profile_selected", {
            "symbol": symbol,
            "strategy": strategy,
            "exit_profile": decision.suggested_exit_profile.name.value,
            "first_take_profit_pct": decision.suggested_exit_profile.first_take_profit_pct,
            "time_stop_sec": decision.suggested_exit_profile.time_stop_sec,
            "trailing_stop_pct": decision.suggested_exit_profile.trailing_stop_pct,
            "runner_take_profit_pct": decision.suggested_exit_profile.runner_take_profit_pct,
        })
        self._strategy_journal.record_order_event("runner_decision", {
            "symbol": symbol,
            "strategy": strategy,
            "runner_allowed": decision.runner_allowed,
            "edge_quality": decision.edge_quality.value,
            "current_regime": regime.regime.value,
            "microprice_edge": inputs.microprice_edge,
            "orderbook_pressure": inputs.orderbook_pressure,
        })
        return decision

    async def _observe_live_guard_timeout(self, reason: str) -> None:
        trip = self._live_guard.observe_order_timeout()
        if trip:
            logger.critical("[LiveGuard] %s source=%s — kill_switch", trip, reason)
            await self.kill_switch(KillReason.LIVE_GUARD)

    async def _observe_live_guard_slippage(self, slippage_pct: float, *, symbol: str, side: str) -> None:
        trip = self._live_guard.observe_slippage(slippage_pct)
        if trip:
            logger.critical(
                "[LiveGuard] %s symbol=%s side=%s slippage=%.3f%% — kill_switch",
                trip, symbol, side, slippage_pct * 100,
            )
            await self.kill_switch(KillReason.LIVE_GUARD)

    @staticmethod
    def _select_live_strategy_signal(signals: list[StrategySignal]) -> Optional[StrategySignal]:
        live = [s for s in signals if s.live_allowed and not s.shadow_only and s.entry_price is not None]
        if not live:
            return None
        return sorted(live, key=lambda s: (s.expected_edge_pct, s.confidence), reverse=True)[0]

    @staticmethod
    def _strategy_signal_to_event(signal: StrategySignal, tick: TickEvent) -> SignalEvent:
        return SignalEvent(
            symbol=signal.symbol,
            score=max(0.0, min(100.0, signal.confidence * 100.0)),
            action="enter_now" if signal.side == "buy" else "exit",
            reason=f"{signal.strategy_name}:{signal.reason}",
            exec_strength=float(signal.metrics.get("exec_strength", 0.0) or 0.0),
            ob_imbalance=float(signal.metrics.get("ob_imbalance", 1.0) or 1.0),
            vwap_gap=float(signal.metrics.get("vwap_gap", 0.0) or 0.0),
            atr=float(signal.metrics.get("atr", 0.0) or 0.0),
            price=signal.entry_price or tick.price,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # 진입 처리 (중복 방지 + symbol_lock)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_entry_signal(self, sig: Any, tick: TickEvent) -> None:
        symbol = tick.symbol
        if not self._position_mgr or not self._risk_mgr or not self._executor:
            return
        # 전략 루프 전용
        if self._status != BotStatus.RUNNING:
            return
        if self._broker_reconcile_blocked:
            self._record_entry_reject(
                symbol=symbol,
                strategy=getattr(sig, "reason", "current_strategy"),
                reason="broker_reconcile_blocked",
                stage="order",
                sig=sig,
                tick=tick,
            )
            return

        # BUG-40 FIX: exit이 진행 중이면 진입 즉시 취소
        if symbol in self._cancel_entry_for:
            return

        if symbol not in self._entry_locks:
            self._entry_locks[symbol] = asyncio.Lock()
        if self._entry_locks[symbol].locked():
            return

        async with self._entry_locks[symbol]:
            # lock 획득 후 재확인 (exit이 lock 대기 중에 발생한 경우)
            if symbol in self._cancel_entry_for:
                self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="exit_in_progress", stage="order", sig=sig, tick=tick)
                return
            if symbol in self._active_order_symbols:
                self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="duplicate_symbol_blocked", stage="order", sig=sig, tick=tick)
                return
            if symbol in self._position_mgr.active_positions():
                self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="duplicate_symbol_blocked", stage="order", sig=sig, tick=tick)
                return

            active = self._position_mgr.active_positions()

            # CLOSE_BET / UNKNOWN 포지션 충돌 방지 ─────────────────────────────
            # 같은 종목 CLOSE_BET 미청산 → 신규 INTRADAY 진입 금지
            for _sym, _pos in active.items():
                if _pos.position_type == PositionType.CLOSE_BET:
                    logger.warning(
                        "Entry blocked: %s — CLOSE_BET position exists for %s (pending clearance)",
                        symbol, _sym,
                    )
                    self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="closebet_position_blocked", stage="order", sig=sig, tick=tick)
                    return
                if _pos.position_type == PositionType.UNKNOWN:
                    logger.warning(
                        "Entry blocked: %s — UNKNOWN position exists for %s (manual review needed)",
                        symbol, _sym,
                    )
                    self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="unknown_position_blocked", stage="order", sig=sig, tick=tick)
                    return

            # 스프레드 체크 + 레짐 정책 적용
            policy = self._regime_analyzer.current_policy
            effective_spread_limit = policy.max_entry_spread_pct or MAX_ENTRY_SPREAD_PCT
            if tick.ask1_price > 0 and tick.bid1_price > 0:
                spread_pct = (tick.ask1_price - tick.bid1_price) / tick.price
                self._regime_analyzer.record_spread(spread_pct)
                if spread_pct > effective_spread_limit:
                    logger.debug(
                        "Entry blocked: %s spread=%.3f%% > max=%.3f%% [regime=%s]",
                        symbol, spread_pct * 100, effective_spread_limit * 100, policy.regime.value,
                    )
                    self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="spread_too_wide", stage="order", sig=sig, tick=tick)
                    return

            # ATR 대비 왕복 비용 필터: ATR < 비용 × MIN_ATR_COST_RATIO 이면 수익 불가
            atr_for_check = self._signal_engine.get_atr(symbol)
            if atr_for_check > 0 and tick.price > 0:
                round_trip_cost = tick.price * (COMMISSION_RATE * 2 + TAX_RATE_KOSDAQ)
                if atr_for_check < round_trip_cost * MIN_ATR_COST_RATIO:
                    logger.debug(
                        "Entry blocked: %s ATR=%.0f < cost_threshold=%.0f",
                        symbol, atr_for_check, round_trip_cost * MIN_ATR_COST_RATIO,
                    )
                    self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="atr_cost_ratio_below", stage="order", sig=sig, tick=tick)
                    return

            # 슬리피지 포함 기대수익 필터
            if atr_for_check > 0 and tick.price > 0:
                expected_gain = atr_for_check * ATR_TRAIL_MULTIPLIER
                slippage_cost = tick.price * (EXPECTED_ENTRY_SLIPPAGE_PCT + EXPECTED_EXIT_SLIPPAGE_PCT)
                total_cost = round_trip_cost + slippage_cost  # type: ignore[possibly-undefined]
                if expected_gain < total_cost * MIN_PROFIT_COST_RATIO:
                    logger.debug(
                        "Entry blocked: %s expected_gain=%.0f < cost×%.0f=%.0f",
                        symbol, expected_gain, MIN_PROFIT_COST_RATIO, total_cost * MIN_PROFIT_COST_RATIO,
                    )
                    self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="expected_edge_below_cost", stage="order", sig=sig, tick=tick)
                    return

            # ask1 기반 진입 가격: 신호 가격 대비 +0.3% 이내만 허용
            entry_price = tick.price
            if tick.ask1_price > 0:
                if tick.ask1_price > tick.price * 1.003:
                    logger.debug(
                        "Entry blocked: %s ask1=%.0f > signal×1.003=%.0f",
                        symbol, tick.ask1_price, tick.price * 1.003,
                    )
                    self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="slippage_limit", stage="order", sig=sig, tick=tick)
                    return
                entry_price = tick.ask1_price

            qty = await self._calc_entry_qty(symbol, entry_price)
            strategy_id_for_gate = self._entry_strategy_id(sig)
            snapshot = self._signal_engine.get_signal_snapshot(symbol)
            promotion_state = self._promotion_gate.state_for(strategy_id_for_gate)
            runtime = self._runtime_permission_gate.evaluate(
                strategy=strategy_id_for_gate,
                promotion_state=promotion_state,
                regime=self._current_runtime_regime(),
                execution_quality=self._current_execution_quality(),
                market_phase=str(self._strategy_schedule_snapshot().get("market_phase", "")).upper(),
                last_tick_age_sec=snapshot.get("last_tick_age_sec"),
                stale_feature_age_sec=snapshot.get("last_tick_age_sec"),
                metrics={
                    "score": getattr(sig, "score", 0.0),
                    "reason": getattr(sig, "reason", ""),
                    "spread_pct": (
                        (tick.ask1_price - tick.bid1_price) / tick.price
                        if tick.price > 0 and tick.ask1_price > 0 and tick.bid1_price > 0
                        else 0.0
                    ),
                    **snapshot,
                },
            )
            self._record_runtime_permission(runtime)
            if not runtime.allowed:
                self._record_entry_reject(
                    symbol=symbol,
                    strategy=strategy_id_for_gate,
                    reason=runtime.blocked_reason,
                    stage="order",
                    sig=sig,
                    tick=tick,
                )
                return
            quote_health = self._quote_health_from_tick(tick)
            if quote_health.latency_state == LatencyState.DANGER:
                self._record_entry_reject(
                    symbol=symbol,
                    strategy=strategy_id_for_gate,
                    reason=quote_health.blocked_reason or "latency_state_danger",
                    stage="order",
                    sig=sig,
                    tick=tick,
                    extra_metrics=quote_health.to_dict(),
                )
                self._record_gatekeeper_snapshot(
                    record_id=self._strategy_journal.record_id_for(symbol, strategy_id_for_gate),
                    symbol=symbol,
                    strategy=strategy_id_for_gate,
                    final_decision="block",
                    signal_score=float(getattr(sig, "score", 0.0) or 0.0),
                    promotion_state=promotion_state.value,
                    runtime_permission=runtime.runtime_permission,
                    terminal_blocker=quote_health.blocked_reason or "latency_state_danger",
                    blocker_reason=quote_health.blocked_reason or "latency_state_danger",
                    feature_snapshot={**snapshot, **quote_health.to_dict()},
                )
                return
            if runtime.allowed_size_ratio > 0:
                qty = max(1, int(qty * runtime.allowed_size_ratio)) if qty > 0 else 0
            if quote_health.latency_state == LatencyState.CAUTION and qty > 0:
                qty = max(1, int(qty * 0.5))
            if qty <= 0:
                self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="qty_zero", stage="order", sig=sig, tick=tick)
                return

            micro_ok, micro_reason, micro_metrics = self._evaluate_microprice_entry_gate(
                symbol=symbol,
                strategy=strategy_id_for_gate,
                tick=tick,
                qty=qty,
                snapshot=snapshot,
            )
            if not micro_ok:
                self._record_entry_reject(
                    symbol=symbol,
                    strategy=strategy_id_for_gate,
                    reason=micro_reason,
                    stage="order",
                    sig=sig,
                    tick=tick,
                    extra_metrics=micro_metrics,
                )
                return

            edge_decision = self._evaluate_expected_edge_gate(
                symbol=symbol,
                strategy=strategy_id_for_gate,
                sig=sig,
                tick=tick,
                snapshot=snapshot,
                runtime=runtime,
                micro_metrics=micro_metrics,
            )
            if edge_decision.reject_reason:
                self._record_entry_reject(
                    symbol=symbol,
                    strategy=strategy_id_for_gate,
                    reason=edge_decision.reject_reason,
                    stage="order",
                    sig=sig,
                    tick=tick,
                    extra_metrics=edge_decision.to_dict(),
                )
                return
            if edge_decision.degrade_to_shadow:
                self._record_entry_reject(
                    symbol=symbol,
                    strategy=strategy_id_for_gate,
                    reason=edge_decision.warning_reason or "expected_edge_degrade_to_shadow",
                    stage="order",
                    sig=sig,
                    tick=tick,
                    extra_metrics=edge_decision.to_dict(),
                )
                return
            if edge_decision.suggested_position_multiplier > 0:
                qty = max(1, int(qty * min(1.0, edge_decision.suggested_position_multiplier)))

            amount = entry_price * qty
            total_exposure = sum(
                p.avg_price * p.remaining_qty for p in active.values()
            )
            approved, reason = self._risk_mgr.approve_entry(
                symbol=symbol,
                amount=amount,
                current_positions_count=len(active),
                total_exposure=total_exposure,
                market_strength_ok=(
                    self._scanner.kosdaq_change_pct > -0.015
                    if self._scanner else True
                ),
                max_symbols_override=policy.max_symbols,
                max_position_pct_override=policy.max_position_pct if policy.max_position_pct > 0 else None,
                max_total_exposure_pct_override=policy.max_total_exposure_pct if policy.max_total_exposure_pct > 0 else None,
                strategy_name=strategy_id_for_gate,
                max_daily_trades_override=runtime.max_daily_trades,
                max_trades_per_strategy_override=runtime.max_trades_per_strategy,
            )
            if not approved:
                logger.debug("Entry blocked: %s — %s", symbol, reason)
                self._record_entry_reject(symbol=symbol, strategy=getattr(sig, "reason", "current_strategy"), reason="risk_blocked", stage="order", sig=sig, tick=tick)
                return

            self._active_order_symbols.add(symbol)
            try:
                signal_event_id = f"{symbol}:{strategy_id_for_gate}:{int(time.time() * 1000)}"
                req = OrderRequest(
                    symbol=symbol, side="buy",
                    qty=qty, price=entry_price,
                    order_type="limit", reason="entry_1",
                    ref_id=signal_event_id,
                )
                self._strategy_journal.record_order_event("live_order_attempt", {
                    "symbol": symbol,
                    "side": "buy",
                    "qty": qty,
                    "expected_entry_price": entry_price,
                    "strategy": getattr(sig, "reason", "current_strategy"),
                    "strategy_id": self._entry_strategy_id(sig),
                    "score": getattr(sig, "score", 0.0),
                    "signal_event_id": signal_event_id,
                    "execution_policy": "maker_first_ask1_limit",
                    "max_requotes": 1,
                    "cancel_after_ms": 2000,
                })
                self._live_order_attempt_count += 1
                force_sim = self._promotion_gate.is_dry_run_live(strategy_id_for_gate)
                order_no = await self._executor.submit(req, force_simulate=force_sim)
                if not order_no:
                    self._strategy_journal.record_order_event("live_order_timeout", {
                        "symbol": symbol,
                        "side": "buy",
                        "qty": qty,
                        "expected_entry_price": entry_price,
                        "reject_reason": "submit_failed",
                        "dry_run_live": force_sim,
                    })
                    await self._observe_live_guard_timeout("entry_submit_failed")
                    return

                fill = await self._executor.wait_fill(order_no, timeout=2.0)

                # BUG-40 FIX: wait_fill 대기 중 exit이 발생한 경우 진입 취소
                if symbol in self._cancel_entry_for:
                    logger.warning(
                        "Entry cancelled mid-flight for %s (exit triggered during wait_fill)",
                        symbol,
                    )
                    try:
                        await self._executor.cancel_pending(order_no)
                    except Exception:
                        pass
                    return

                if not fill:
                    self._strategy_journal.record_order_event("live_order_timeout", {
                        "symbol": symbol,
                        "order_no": order_no,
                        "side": "buy",
                        "qty": qty,
                        "expected_entry_price": entry_price,
                        "order_timeout": True,
                        "signal_event_id": signal_event_id,
                        "execution_policy": "maker_first_ask1_limit",
                    })
                    await self._observe_live_guard_timeout("entry_wait_fill_timeout")
                    if self._status != BotStatus.RUNNING or symbol in self._cancel_entry_for:
                        return

                    requote_price = tick.ask1_price if tick.ask1_price > 0 else entry_price
                    requote_ok, requote_reason, requote_metrics = self._evaluate_microprice_entry_gate(
                        symbol=symbol,
                        strategy=strategy_id_for_gate,
                        tick=tick,
                        qty=qty,
                        snapshot=snapshot,
                    )
                    if not requote_ok:
                        self._record_entry_reject(
                            symbol=symbol,
                            strategy=strategy_id_for_gate,
                            reason=requote_reason,
                            stage="order",
                            sig=sig,
                            tick=tick,
                            extra_metrics=requote_metrics,
                        )
                        return

                    requote_event_id = f"{signal_event_id}:rq1"
                    requote_req = OrderRequest(
                        symbol=symbol, side="buy",
                        qty=qty, price=requote_price,
                        order_type="limit", reason="entry_1",
                        ref_id=requote_event_id,
                    )
                    self._strategy_journal.record_order_event("live_order_attempt", {
                        "symbol": symbol,
                        "side": "buy",
                        "qty": qty,
                        "expected_entry_price": requote_price,
                        "strategy": getattr(sig, "reason", "current_strategy"),
                        "strategy_id": strategy_id_for_gate,
                        "score": getattr(sig, "score", 0.0),
                        "signal_event_id": requote_event_id,
                        "execution_policy": "maker_first_ask1_limit",
                        "replace_count": 1,
                        "replace_reason": "entry_timeout_requote",
                        "cancel_after_ms": 2000,
                    })
                    self._live_order_attempt_count += 1
                    order_no = await self._executor.submit(requote_req)
                    if not order_no:
                        self._strategy_journal.record_order_event("live_order_timeout", {
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "expected_entry_price": requote_price,
                            "reject_reason": "requote_submit_failed",
                            "signal_event_id": requote_event_id,
                        })
                        await self._observe_live_guard_timeout("entry_requote_submit_failed")
                        return
                    fill = await self._executor.wait_fill(order_no, timeout=2.0)
                    if symbol in self._cancel_entry_for:
                        try:
                            await self._executor.cancel_pending(order_no)
                        except Exception:
                            pass
                        return
                    if not fill:
                        self._strategy_journal.record_order_event("live_order_timeout", {
                            "symbol": symbol,
                            "order_no": order_no,
                            "side": "buy",
                            "qty": qty,
                            "expected_entry_price": requote_price,
                            "order_timeout": True,
                            "signal_event_id": requote_event_id,
                            "execution_policy": "maker_first_ask1_limit",
                            "replace_count": 1,
                        })
                        await self._observe_live_guard_timeout("entry_requote_wait_fill_timeout")
                        return
                    entry_price = requote_price

                atr = self._signal_engine.get_atr(symbol) or self._scanner.get_atr(symbol).atr
                strategy_id = strategy_id_for_gate
                pos = self._position_mgr.on_fill_entry(fill, atr, strategy_id=strategy_id)
                self._risk_mgr.record_entry(symbol, strategy_name=strategy_id)
                await self._save_position(symbol)

                snap = self._signal_engine.get_signal_snapshot(symbol)
                slippage_exceeded, slippage = self._executor.check_slippage(
                    entry_price, fill.fill_price, "buy"
                )
                if slippage_exceeded:
                    await self._observe_live_guard_slippage(slippage, symbol=symbol, side="buy")
                self._strategy_journal.record_order_event("live_order_fill", {
                    "symbol": symbol,
                    "order_no": order_no,
                    "side": "buy",
                    "qty": fill.filled_qty,
                    "expected_entry_price": entry_price,
                    "actual_entry_price": fill.fill_price,
                    "entry_slippage": slippage,
                    "partial_fill": fill.filled_qty < qty,
                    "strategy": getattr(sig, "reason", "current_strategy"),
                    "strategy_id": strategy_id,
                })
                self._live_fill_count += 1
                self._strategy_journal.record_order_event("slippage_report", {
                    "symbol": symbol,
                    "order_no": order_no,
                    "side": "buy",
                    "expected_price": entry_price,
                    "actual_price": fill.fill_price,
                    "slippage_pct": slippage,
                })
                self._journal.record_entry(
                    symbol=symbol, order_no=order_no,
                    fill_price=fill.fill_price,
                    expected_price=entry_price,
                    qty=fill.filled_qty,
                    commission=fill.commission,
                    slippage_pct=slippage,
                    score=sig.score,
                    exec_strength=snap.get("exec_strength", 0),
                    ob_imbalance=snap.get("ob_imbalance", 0),
                    vwap_gap=snap.get("vwap_gap", 0),
                    atr=snap.get("atr", 0),
                    vol_ratio=snap.get("vol_ratio", 0),
                    market_kosdaq_pct=self._scanner.kosdaq_change_pct if self._scanner else 0,
                    regime=self._regime_analyzer.current_regime.value,
                )
                if self._store:
                    await self._store.log_trade({
                        **self._journal.get_today()[-1],
                        "type": "entry",
                    })

                logger.info(
                    "ENTRY: %s qty=%d price=%.0f score=%.1f atr=%.0f",
                    symbol, fill.filled_qty, fill.fill_price, sig.score, atr,
                )
            finally:
                self._active_order_symbols.discard(symbol)
                self._cancel_entry_for.discard(symbol)

    # ═══════════════════════════════════════════════════════════════════════════
    # 청산 처리 (전략 루프에서 호출 — RUNNING only)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_exit(
        self, req: OrderRequest, expected_price: float = 0.0, bid1_price: float = 0.0
    ) -> None:
        symbol = req.symbol

        # BUG-40 FIX: exit 시작 즉시 entry 취소 신호 — entry lock 대기 없이 선점
        self._cancel_entry_for.add(symbol)

        if symbol not in self._exit_locks:
            self._exit_locks[symbol] = asyncio.Lock()

        # bid1 기반 청산 가격 설정 — 손절/강제청산/break-even은 시장가이므로 제외
        _MARKET_EXIT_REASONS = {"exit_sl", "exit_be_stop", "kill_switch"}
        if (bid1_price > 0
                and req.order_type == "limit"
                and req.reason not in _MARKET_EXIT_REASONS):
            import dataclasses as _dc
            req = _dc.replace(req, price=bid1_price)

        async with self._exit_locks[symbol]:
            self._strategy_journal.record_order_event("live_order_attempt", {
                "symbol": symbol,
                "side": "sell",
                "qty": req.qty,
                "expected_exit_price": req.price or expected_price,
                "reason": req.reason,
                "position_type": req.position_type.value,
            })
            self._live_order_attempt_count += 1
            order_no = await self._executor.submit(req)
            if not order_no:
                order_no = await self._executor.submit_market(req)

            fill: Optional[FillEvent] = None
            if order_no:
                fill = await self._executor.wait_fill(order_no)

            if not fill:
                logger.error("Exit fill failed: %s reason=%s", symbol, req.reason)
                self._strategy_journal.record_order_event("live_order_timeout", {
                    "symbol": symbol,
                    "side": "sell",
                    "qty": req.qty,
                    "expected_exit_price": req.price or expected_price,
                    "reason": req.reason,
                    "order_timeout": True,
                })
                await self._observe_live_guard_timeout("exit_wait_fill_timeout")
                return

            pre_exit_pos = self._position_mgr.get_position(symbol)
            was_close_bet = bool(
                pre_exit_pos
                and pre_exit_pos.position_type == PositionType.CLOSE_BET
            )
            entry_price_for_gap = pre_exit_pos.avg_price if pre_exit_pos else 0.0
            pos = self._position_mgr.on_fill_exit(fill)
            if not pos:
                return

            pnl = (fill.fill_price - pos.avg_price) * fill.filled_qty
            net_pnl = pnl - fill.commission - fill.tax
            is_partial = req.reason.startswith("exit_tp")

            self._risk_mgr.record_trade(
                symbol=symbol,
                realized_pnl=net_pnl,
                commission=fill.commission,
                is_partial=is_partial,
            )

            if pos.phase == PositionPhase.CLOSED:
                if self._store:
                    await self._store.delete_position(symbol)
                # fake breakout ratio 갱신 (손절=실패, 익절=성공)
                if req.reason == "exit_sl":
                    self._regime_analyzer.record_breakout_result(False)
                elif net_pnl > 0:
                    self._regime_analyzer.record_breakout_result(True)
            else:
                await self._save_position(symbol)

            exit_slippage_exceeded, exit_slippage = self._executor.check_slippage(
                expected_price, fill.fill_price, "sell"
            ) if expected_price > 0 else (False, 0.0)
            if exit_slippage_exceeded:
                await self._observe_live_guard_slippage(exit_slippage, symbol=symbol, side="sell")
            self._strategy_journal.record_order_event("live_order_fill", {
                "symbol": symbol,
                "order_no": fill.order_no,
                "side": "sell",
                "qty": fill.filled_qty,
                "expected_exit_price": expected_price,
                "actual_exit_price": fill.fill_price,
                "exit_slippage": exit_slippage,
                "partial_fill": fill.filled_qty < req.qty,
                "reason": req.reason,
            })
            self._live_fill_count += 1
            self._strategy_journal.record_order_event("slippage_report", {
                "symbol": symbol,
                "order_no": fill.order_no,
                "side": "sell",
                "expected_price": expected_price,
                "actual_price": fill.fill_price,
                "slippage_pct": exit_slippage,
            })
            rec = self._journal.record_exit(
                symbol=symbol, order_no=fill.order_no,
                fill_price=fill.fill_price,
                expected_price=expected_price,
                qty=fill.filled_qty,
                commission=fill.commission, tax=fill.tax,
                slippage_pct=exit_slippage,
                net_pnl=net_pnl, reason=req.reason,
                position_type=pos.position_type.value,
                metadata={
                    "gap_pct": gap_pct(entry_price_for_gap, fill.fill_price),
                    "exit_reason": req.reason,
                    "holding_overnight": was_close_bet,
                    "listing_market": enum_value(req.listing_market),
                    "execution_venue": enum_value(req.execution_venue),
                    "preferred_venue": enum_value(req.preferred_venue),
                    "actual_venue": enum_value(req.actual_venue),
                    "venue_policy": enum_value(req.venue_policy),
                    "market_session": enum_value(req.market_session),
                    "krx_reference_price": entry_price_for_gap,
                    "nxt_pre_signal": pos.nxt_pre_signal,
                },
            )
            if self._store:
                await self._store.log_trade({**rec.to_dict(), "type": "exit"})
            if was_close_bet and (
                req.reason.startswith("exit_next_open")
                or req.reason.startswith("exit_preopen")
            ):
                self._closing_bet_results.append({
                    **rec.to_dict(),
                    "entry_price": entry_price_for_gap,
                    "entry_time": "",
                    "exit_price": fill.fill_price,
                    "exit_time": datetime.now().strftime("%H:%M:%S"),
                    "exit_reason": req.reason,
                })

            logger.info(
                "EXIT: %s reason=%s pnl=%.0f phase=%s",
                symbol, req.reason, net_pnl, pos.phase.value,
            )

        # BUG-40 FIX: exit 완료 후 entry 취소 플래그 해제
        self._cancel_entry_for.discard(symbol)

    @staticmethod
    def _entry_strategy_id(sig: Any) -> str:
        reason = str(getattr(sig, "reason", "") or "")
        if ":" in reason:
            strategy = reason.split(":", 1)[0]
            if strategy == "shallow_pullback":
                return "leader_only_shallow_pullback"
            return strategy
        if reason.startswith("leader_shallow_pullback"):
            return "leader_only_shallow_pullback"
        if reason.startswith("pullback_breakout"):
            return "deep_pullback"
        return "intraday_scalp"

    # ═══════════════════════════════════════════════════════════════════════════
    # 전략 루프 (RUNNING only)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _index_monitor_loop(self) -> None:
        """
        KOSDAQ 지수 1초 간격 독립 갱신.
        _scan_loop 주기(3초)와 분리해 지수 급락 즉시 감지.
        서킷브레이커(-8%) 감지 시 Kill Switch.
        """
        await asyncio.sleep(5.0)  # 초기 워밍업
        # BUG-03 FIX: _is_active() — PAUSED 중에도 지수 모니터링 유지
        while _is_active(self._status) and not self._kill_event.is_set():
            try:
                if self._scanner:
                    pct = await self._scanner.update_kosdaq_index()
                    if self._risk_mgr:
                        self._risk_mgr.update_kosdaq(pct)
                        if self._risk_mgr.is_halted and _is_active(self._status):
                            # BUG-26 FIX: halt_type 기반 정확한 kill_reason — kill_switch() 내부에서 매핑
                            await self.kill_switch(KillReason.DAILY_LOSS)
                            return
                    if pct <= CIRCUIT_BREAKER_THRESHOLD and not self._market_halted:
                        logger.critical(
                            "Circuit breaker triggered: KOSDAQ %.2f%% <= %.0f%% — suspending entries",
                            pct * 100, CIRCUIT_BREAKER_THRESHOLD * 100,
                        )
                        self._market_halted = True
                        # BUG-37 FIX: 즉시 kill 대신 재개 대기 루프 시작
                        asyncio.create_task(self._cb_recovery_loop())
            except Exception as exc:
                logger.debug("_index_monitor_loop error: %s", exc)
            await asyncio.sleep(1.0)
        logger.info("Index monitor loop stopped. status=%s", self._status.value)

    async def _cb_recovery_loop(self) -> None:
        """서킷브레이커 해제 감지 루프 (BUG-37 FIX).

        CB 발동 → 신규 진입 차단 → 30초마다 지수 재확인
        → 지수 회복 시 거래 재개 / SOFT_CLOSE_TIME 도달 시 kill_switch.
        """
        CB_RECOVERY_THRESHOLD = CIRCUIT_BREAKER_THRESHOLD * 0.7  # -8% → -5.6% 이상 시 재개
        logger.critical(
            "[CB] Circuit breaker active. Polling recovery every %.0fs.", CB_RESUME_POLL_SECS
        )
        while self._market_halted and _is_active(self._status):
            await asyncio.sleep(CB_RESUME_POLL_SECS)

            now = datetime.now().time()
            if now >= SOFT_CLOSE_TIME:
                logger.critical("[CB] Still active at close time — kill_switch")
                await self.kill_switch(KillReason.CIRCUIT_BREAKER)
                return

            if not self._scanner:
                continue

            try:
                pct = await self._scanner.update_kosdaq_index()
                if self._risk_mgr:
                    self._risk_mgr.update_kosdaq(pct)
                if pct > CB_RECOVERY_THRESHOLD:
                    self._market_halted = False
                    logger.warning(
                        "[CB] Circuit breaker lifted (KOSDAQ=%.2f%%) — resuming trading",
                        pct * 100,
                    )
                    return
                logger.info("[CB] Still halted: KOSDAQ=%.2f%%", pct * 100)
            except Exception as exc:
                logger.debug("[CB] Recovery check error: %s", exc)

        logger.info("[CB] Recovery loop ended. market_halted=%s", self._market_halted)

    async def _scan_loop(self) -> None:
        SCAN_INTERVAL = 3.0
        # BUG-03 FIX: _is_active() — PAUSED 중에도 스캔/레짐 업데이트 유지
        while _is_active(self._status) and not self._kill_event.is_set():
            now = datetime.now().time()
            if (MARKET_OPEN <= now < SCAN_WINDOW_END
                    and not self._risk_mgr.is_halted):
                try:
                    # KOSPI_DEFENSIVE 레짐에서는 대형주 유니버스로 제한
                    policy = self._regime_analyzer.current_policy
                    whitelist = (
                        KOSPI_LARGE_CAP_UNIVERSE
                        if policy.universe == "kospi_large_cap"
                        else None
                    )
                    candidates = await self._scanner.run_scan(whitelist=whitelist)
                except Exception as exc:
                    logger.error("scan_loop error: %s", exc)
                    candidates = []

                # 레짐 점수 업데이트 — API 실패(0 items)면 스킵해 히스테리시스 타이머 보호
                if self._scanner.last_scan_had_data:
                    regime, reg_score = self._regime_analyzer.update(
                        kosdaq_change_pct=self._scanner.kosdaq_change_pct,
                        top_candidates=candidates,
                    )
                    logger.info(
                        "[Regime] %s score=%.0f fb=%.0f%% vi=%d spread=%.3f%% top_chg=%.1f%%",
                        regime.value, reg_score.total,
                        reg_score.fake_breakout_ratio * 100,
                        reg_score.vi_count_30m,
                        reg_score.spread_avg * 100,
                        reg_score.avg_top_change_pct * 100,
                    )
                else:
                    self._regime_analyzer.note_scan_stale(self._scanner.last_scan_source_status)

                new_symbols = []
                if candidates:
                    self._shadow_engine.observe_candidates(candidates)
                    self._record_candidate_provenance(candidates)
                    logger.info(
                        "[ScanCandidates] count=%d candidates=%s",
                        len(candidates),
                        ",".join(
                            f"{c.symbol}:{c.name or '-'}:{c.change_pct * 100:.2f}%"
                            for c in candidates[:20]
                        ),
                    )
                else:
                    self._shadow_engine.flush_windows()

                self._update_execution_quality(emit=True)
                runtime_regime = self._update_runtime_regime(candidates)

                strategy_context = StrategyContext(
                    now_time=datetime.now().time(),
                    regime=runtime_regime.regime.value,
                    market_ok=runtime_regime.regime not in {RuntimeRegime.NO_TRADE, RuntimeRegime.CONFIRMING},
                )
                strategy_candidates = self._strategy_router.route_candidates(candidates, strategy_context)
                activations = self._strategy_router.select_active_strategies(
                    datetime.now().time(),
                    runtime_regime.regime.value,
                    {},
                )
                top_near_miss = [
                    {
                        "symbol": c.symbol,
                        "strategy": c.strategy_name,
                        "reason": c.reason,
                        "leader_rank": c.metrics.get("leader_rank"),
                        "leader_score": c.metrics.get("leader_score"),
                    }
                    for c in strategy_candidates
                    if "near_miss" in c.strategy_name or "near_miss" in c.reason
                ][:10]
                self._strategy_journal.record_route_summary(
                    raw_scan_count=self._scanner.last_raw_count,
                    after_etf_filter_count=self._scanner.last_after_etf_filter_count,
                    after_liquidity_filter_count=len(candidates),
                    after_regime_filter_count=(
                        len(candidates)
                        if self._regime_analyzer.current_policy.regime != MarketRegime.NO_TRADE
                        else 0
                    ),
                    candidates=strategy_candidates,
                    strategy_signal_count_by_strategy=self._last_strategy_signal_counts,
                    shadow_entry_count_by_strategy=self._shadow_entry_counts,
                    live_order_attempt_count=self._live_order_attempt_count,
                    fill_count=self._live_fill_count,
                    top_rejected_reasons=self._scanner.last_reject_counts,
                    top_near_miss_symbols=top_near_miss,
                    stale_feature_ratio=(
                        self._stale_feature_samples / self._freshness_samples
                        if self._freshness_samples else 0.0
                    ),
                    active_strategies=[a.name.value for a in activations],
                    current_schedule=self._current_schedule_name(),
                    market_regime=runtime_regime.regime.value,
                )
                if runtime_regime.regime in {RuntimeRegime.NO_TRADE, RuntimeRegime.CONFIRMING}:
                    for c in candidates[:20]:
                        self._strategy_journal.record_reject(
                            symbol=c.symbol,
                            name=c.name,
                            strategy="router",
                            stage="route",
                            reject_reason=f"regime_{runtime_regime.regime.value}",
                            metrics={
                                "change_pct": c.change_pct,
                                "trading_value": c.trading_value,
                                "leader_rank": c.leader_rank,
                                "leader_score": c.leader_score,
                            },
                            market_regime=self._regime_analyzer.current_regime.value,
                            schedule=self._current_schedule_name(),
                            feature_readiness={},
                        )
                        self._shadow_engine.observe_rejected_candidate(
                            c,
                            strategy="router",
                            reject_reason="regime_no_trade",
                            metrics={
                                "change_pct": c.change_pct,
                                "trading_value": c.trading_value,
                                "leader_rank": c.leader_rank,
                                "leader_score": c.leader_score,
                            },
                        )
                routed_symbols = {c.symbol for c in strategy_candidates}
                for c in candidates:
                    if c.symbol not in routed_symbols:
                        self._strategy_journal.record_reject(
                            symbol=c.symbol,
                            name=c.name,
                            strategy="router",
                            stage="route",
                            reject_reason="no_strategy_candidate",
                            metrics={
                                "change_pct": c.change_pct,
                                "trading_value": c.trading_value,
                                "vol_ratio": c.vol_ratio,
                                "leader_rank": c.leader_rank,
                                "leader_score": c.leader_score,
                            },
                            market_regime=self._regime_analyzer.current_regime.value,
                            schedule=self._current_schedule_name(),
                            feature_readiness={},
                        )
                        self._shadow_engine.observe_rejected_candidate(
                            c,
                            strategy="router",
                            reject_reason="no_strategy_candidate",
                            metrics={
                                "change_pct": c.change_pct,
                                "trading_value": c.trading_value,
                                "vol_ratio": c.vol_ratio,
                                "leader_rank": c.leader_rank,
                                "leader_score": c.leader_score,
                            },
                        )
                for c in candidates:
                    self._candidate_cache[c.symbol] = c  # 최신 스캔 정보 캐싱
                    self._signal_engine.update_scan_context(
                        c.symbol,
                        price=c.price,
                        vol_ratio=c.vol_ratio,
                        leader_rank=getattr(c, "leader_rank", 999),
                        leader_score=getattr(c, "leader_score", 0.0),
                    )

                    atr_st = self._scanner.get_atr(c.symbol)
                    if atr_st.ready:
                        st = self._signal_engine.get_symbol_state(c.symbol)
                        if st:
                            st.atr = atr_st

                    if c.symbol not in self._watchlist:
                        self._watchlist.add(c.symbol)
                        new_symbols.append(c.symbol)

                if new_symbols:
                    self._ws_symbols = list(self._watchlist)
                    now_ts = time.monotonic()
                    if not self._cfg.strategy.dry_run:
                        if not self._ws_subscriber:
                            # 최초 구독
                            await self._start_ws(self._ws_symbols)
                            self._ws_last_resub_ts = now_ts
                        elif now_ts - self._ws_last_resub_ts >= WS_RESUB_COOLDOWN_SECS:
                            # BUG-17 FIX: 쿨다운 경과 후 새 종목 추가 구독
                            logger.info(
                                "[Scan] Re-subscribing WS for %d new symbols: %s",
                                len(new_symbols), new_symbols,
                            )
                            try:
                                self._ws_subscriber.stop()
                            except Exception:
                                pass
                            self._ws_subscriber = None
                            await self._start_ws(self._ws_symbols)
                            self._ws_last_resub_ts = now_ts

            # 오전 스냅샷 — 10:30 첫 도달 시 1회 비동기 실행
            if (not self._morning_snapshot_taken
                    and now >= MORNING_SNAPSHOT_TIME):
                self._morning_snapshot_taken = True
                asyncio.create_task(self._take_morning_snapshot())

            elif now >= SCAN_WINDOW_END:
                # BUG-38 FIX: 스캔 윈도우 종료 후에도 NO_TRADE 조건 실시간 평가
                if self._scanner:
                    self._regime_analyzer.check_hard_no_trade(
                        self._scanner.kosdaq_change_pct
                    )

            await asyncio.sleep(SCAN_INTERVAL)

    def _decide_close_bet_morning_exit(
        self,
        symbol: str,
        pos: Any,
        *,
        current_price: float,
        pre_ctx: Any,
        legacy_reason: str = "",
    ):
        """NXT-aware 익일 오전 청산 판단."""
        now = _dt.datetime.now()
        macro_snapshot = self._macro_feed_engine.snapshot()
        macro_decision = self._macro_risk_model.score(
            macro_snapshot,
            sector=str(getattr(pos, "sector", "") or "default"),
        )
        micro = self._microstructure_engine.snapshot(symbol, ExecutionVenue.NXT, now=now)
        micro_source = "nxt"
        if micro.data_quality == "missing":
            krx_micro = self._microstructure_engine.snapshot(symbol, ExecutionVenue.KRX, now=now)
            if krx_micro.data_quality != "missing":
                micro = krx_micro
                micro_source = "krx_fallback"
        opening = self._opening_candle_engine.snapshot(
            symbol,
            now=now,
            opening_price=current_price,
            previous_close=pos.krx_entry_price or pos.avg_price,
            current_price=current_price,
        )
        pnl_pct = (
            (current_price - pos.avg_price) / pos.avg_price
            if current_price > 0 and pos.avg_price > 0
            else 0.0
        )
        data_quality = self._combine_morning_data_quality(
            macro_decision.data_quality,
            micro.data_quality,
            opening.data_quality,
            nxt_quality=str(getattr(pre_ctx, "data_quality", "missing") or "missing"),
        )
        nxt_gap = float(getattr(pre_ctx, "venue_price_gap", 0.0) or 0.0)
        decision = self._morning_decision_engine.decide(
            MorningDecisionInput(
                symbol=symbol,
                pnl_pct=pnl_pct,
                close_bet_grade=self._close_bet_grade_for_position(pos),
                nxt_discount_pct=min(0.0, nxt_gap),
                macro_risk_score=macro_decision.macro_risk_score,
                fake_bid_risk=None if micro.data_quality == "missing" else micro.fake_bid_risk,
                first_1m_low_break=None if opening.data_quality == "missing" else opening.first_1m_low_break,
                first_3m_high_break=None if opening.data_quality == "missing" else opening.first_3m_high_break,
                vwap_hold=None if opening.data_quality == "missing" else opening.vwap_hold,
                cumulative_bid_delta=None if opening.data_quality == "missing" else opening.cumulative_bid_delta,
                opening_sell_pressure=None if opening.data_quality == "missing" else opening.opening_sell_pressure,
                trading_value_drop_3m=None if opening.data_quality == "missing" else opening.trading_value_drop_3m,
                data_quality=data_quality,
                current_time=now,
            )
        )
        decision.reason_codes.extend(
            [
                f"micro_source:{micro_source}",
                f"macro_quality:{macro_decision.data_quality}",
                f"micro_quality:{micro.data_quality}",
                f"opening_quality:{opening.data_quality}",
                f"nxt_quality:{getattr(pre_ctx, 'data_quality', 'missing')}",
            ]
        )
        if legacy_reason:
            decision.reason_codes.append(f"legacy:{legacy_reason}")
        return decision

    @staticmethod
    def _combine_morning_data_quality(
        macro_quality: str,
        micro_quality: str,
        opening_quality: str,
        *,
        nxt_quality: str = "missing",
    ) -> str:
        qualities = [macro_quality, micro_quality, opening_quality]
        nxt_observed = nxt_quality in {"ok", "full", "partial"}
        if all(q in {"ok", "full"} for q in qualities) and nxt_observed:
            return "full"
        if any(q in {"ok", "full", "partial"} for q in qualities) or nxt_observed:
            return "partial"
        return "missing"

    @staticmethod
    def _close_bet_grade_for_position(pos: Any) -> str:
        signal = str(getattr(pos, "nxt_after_signal", "") or "")
        strategy_id = str(getattr(pos, "strategy_id", "") or "")
        if "a_hold_candidate" in signal or strategy_id.endswith("hold_extension"):
            return "a_hold_candidate"
        if "c_exit_priority" in signal or strategy_id.endswith("exit_priority"):
            return "c_exit_priority"
        return "b_keep_candidate"

    async def _next_open_exit_engine(self) -> None:
        """
        익일 오전 CLOSE_BET 포지션 청산 엔진.
        봇 시작 시 항상 실행 — CLOSE_BET 없으면 즉시 반환.
        우선순위: CLOSE_BET 청산 → 미체결 확인 → 신규 스캔 허용
        """
        if not self._position_mgr:
            return

        # CLOSE_BET 포지션 스냅샷 (시작 시점)
        def _pending() -> dict:
            return {
                sym: pos
                for sym, pos in self._position_mgr.active_positions().items()
                if pos.position_type == PositionType.CLOSE_BET
            }

        if not _pending():
            self._close_bet_exit_done = True
            return

        # 장 시작 대기 (09:00)
        while _is_active(self._status) and not self._kill_event.is_set():
            if datetime.now().time() >= NEXT_OPEN_EXIT_START:
                break
            await asyncio.sleep(5.0)

        logger.info(
            "[NextOpenExit] Market open detected — exiting %d CLOSE_BET position(s): %s",
            len(_pending()), list(_pending().keys()),
        )

        # 09:00 시초 청산 — 현재가 기반 지정가 또는 시장가
        for sym, pos in list(_pending().items()):
            if pos.phase == PositionPhase.CLOSED:
                continue
            current_price = self._signal_engine.get_last_price(sym) if self._signal_engine else 0.0
            pre_ctx = build_nxt_context(
                self._adapter,
                sym,
                session=MarketSession.NXT_PRE,
                env=self._cfg.broker.env,
                krx_reference_price=pos.krx_entry_price or pos.avg_price,
            )
            pre_decision = evaluate_nxt_pre(pre_ctx)
            morning_decision = self._overnight_engine.decide_morning(pre_ctx)
            live_decision = self._decide_close_bet_morning_exit(
                sym,
                pos,
                current_price=current_price,
                pre_ctx=pre_ctx,
                legacy_reason=morning_decision.reason,
            )
            pos.nxt_pre_signal = ",".join(live_decision.reason_codes)
            logger.info(
                "[MorningPositionDecision] symbol=%s %s",
                sym,
                live_decision.to_json(
                    position_type=PositionType.CLOSE_BET.value,
                    strategy_id=pos.strategy_id,
                ),
            )
            if live_decision.action in (MorningAction.HOLD_EXTENSION, MorningAction.NO_ACTION):
                logger.info(
                    "[MorningDecision] HOLD symbol=%s action=%s confidence=%.1f reasons=%s",
                    sym, live_decision.action.value, live_decision.confidence,
                    live_decision.reason_codes,
                )
                continue
            route = choose_routing(
                self._venue_capability,
                requested_policy=VenuePolicy.SOR_BEST_EXECUTION,
                env=self._cfg.broker.env,
                dry_run=self._cfg.strategy.dry_run,
            )
            logger.info(
                "[NXT_PRE] symbol=%s signal=%s reason=%s price=%.0f gap=%.3f%% route=%s fallback=%s morning_action=%s morning_score=%.1f",
                sym, pre_decision.signal.value, pre_decision.reason,
                pre_ctx.nxt_price, pre_ctx.venue_price_gap * 100,
                route.venue_policy.value, route.reason,
                live_decision.action.value, live_decision.confidence,
            )
            exit_qty = pos.remaining_qty
            exit_reason = "exit_next_open"
            if live_decision.action == MorningAction.PREOPEN_EXIT:
                exit_reason = "exit_preopen_risk"
            elif live_decision.action == MorningAction.OPEN_EXIT:
                exit_reason = "exit_open_risk"
            elif live_decision.action == MorningAction.HOLD_TO_0910:
                if live_decision.exit_qty_ratio <= 0:
                    logger.info(
                        "[MorningDecision] HOLD_TO_0910 symbol=%s no_exit reasons=%s",
                        sym, live_decision.reason_codes,
                    )
                    continue
                exit_qty = max(1, int(pos.remaining_qty * live_decision.exit_qty_ratio))
                exit_reason = "exit_hold_to_0910_partial"
            elif morning_decision.action == OvernightAction.PARTIAL_EXIT_THEN_WATCH:
                exit_qty = max(1, pos.remaining_qty // 2)
                exit_reason = "exit_next_open_partial_watch"
            req = OrderRequest(
                symbol=sym,
                side="sell",
                qty=exit_qty,
                price=current_price,
                order_type="limit" if current_price > 0 else "market",
                reason=exit_reason,
                market=pos.market,
                position_type=PositionType.CLOSE_BET,
                order_session="next_open",
                listing_market=pos.listing_market,
                execution_venue=route.actual_venue,
                preferred_venue=route.preferred_venue,
                actual_venue=route.actual_venue,
                venue_policy=route.venue_policy,
                market_session=MarketSession.KRX_OPEN_AUCTION,
            )
            logger.info(
                "[NextOpenExit] Submitting exit: %s qty=%d avg=%.0f current=%.0f",
                sym, pos.remaining_qty, pos.avg_price, current_price,
            )
            asyncio.create_task(self._execute_exit(req, expected_price=current_price))

        # 09:30 데드라인까지 미청산 잔량 모니터링
        while _is_active(self._status) and not self._kill_event.is_set():
            now_t = datetime.now().time()
            remaining = _pending()

            if not remaining:
                logger.info("[NextOpenExit] All CLOSE_BET positions cleared")
                break

            if now_t >= NEXT_DAY_EXIT_DEADLINE:
                logger.warning(
                    "[NextOpenExit] Deadline %s reached — force market exit for %d position(s)",
                    NEXT_DAY_EXIT_DEADLINE, len(remaining),
                )
                for sym, pos in remaining.items():
                    if pos.phase != PositionPhase.CLOSED:
                        req = OrderRequest(
                            symbol=sym, side="sell",
                            qty=pos.remaining_qty, price=0,
                            order_type="market",
                            reason="exit_next_open_deadline",
                            market=pos.market,
                            position_type=PositionType.CLOSE_BET,
                            order_session="next_open",
                            listing_market=pos.listing_market,
                            execution_venue=ExecutionVenue.KRX,
                            preferred_venue=ExecutionVenue.KRX,
                            actual_venue=ExecutionVenue.KRX,
                            venue_policy=VenuePolicy.FALLBACK_KRX,
                            market_session=MarketSession.KRX_OPEN_AUCTION,
                        )
                        asyncio.create_task(self._execute_exit(req))
                break

            await asyncio.sleep(2.0)

        self._close_bet_exit_done = True
        logger.info("[NextOpenExit] Engine complete")

    async def _closing_bet_loop(self) -> None:
        """14:50~15:15 CLOSE_BET 신규 진입 루프."""
        while _is_active(self._status) and not self._kill_event.is_set():
            now = datetime.now().time()
            if self._status != BotStatus.RUNNING:
                await asyncio.sleep(CLOSE_BET_SCAN_INTERVAL_SEC)
                continue
            if not (CLOSE_BET_START_TIME <= now <= CLOSE_BET_END_TIME):
                await asyncio.sleep(CLOSE_BET_SCAN_INTERVAL_SEC)
                continue
            if self._market_halted:
                await asyncio.sleep(CLOSE_BET_SCAN_INTERVAL_SEC)
                continue
            if self._regime_analyzer.current_policy.regime == MarketRegime.NO_TRADE:
                await asyncio.sleep(CLOSE_BET_SCAN_INTERVAL_SEC)
                continue
            if not self._close_bet_scanner:
                await asyncio.sleep(CLOSE_BET_SCAN_INTERVAL_SEC)
                continue

            candidates = self._close_bet_scanner.scan()
            diag = getattr(self._close_bet_scanner, "last_diagnostics", {}) or {}
            for payload in getattr(self._close_bet_scanner, "last_reject_samples", []) or []:
                self._strategy_journal.record_order_event("closebet_near_miss", {
                    **payload,
                    "strategy": "close_bet",
                    "stage": "scan",
                    "accepted": False,
                    "reject_reason": payload.get("reason"),
                    "diagnostics": diag,
                    "market_regime": self._regime_analyzer.current_regime.value,
                    "schedule": self._current_schedule_name(),
                    "friday": datetime.now().weekday() == 4,
                })
            for candidate in candidates:
                if self._status != BotStatus.RUNNING:
                    break
                await self._execute_close_bet_entry(candidate)
            await asyncio.sleep(CLOSE_BET_SCAN_INTERVAL_SEC)

    async def _execute_close_bet_entry(self, candidate: CloseBetCandidate) -> None:
        symbol = candidate.symbol
        if not self._position_mgr or not self._risk_mgr or not self._executor:
            return
        if symbol in self._active_order_symbols:
            return
        if symbol in self._position_mgr.active_positions():
            return
        if symbol not in self._entry_locks:
            self._entry_locks[symbol] = asyncio.Lock()
        if self._entry_locks[symbol].locked():
            return

        async with self._entry_locks[symbol]:
            active = self._position_mgr.active_positions()
            if symbol in active or symbol in self._active_order_symbols:
                return
            intraday_conflict = any(
                s == symbol and p.position_type != PositionType.CLOSE_BET
                for s, p in active.items()
            )
            if intraday_conflict:
                logger.info("CLOSE_BET_ENTRY blocked intraday conflict: %s", symbol)
                return

            capital = self._risk_mgr.state.capital
            if capital <= 0 or candidate.price <= 0:
                return
            size_multiplier = max(0.1, min(1.0, float(candidate.position_size_multiplier or 1.0)))
            max_amount = capital * 0.05 * size_multiplier
            qty = int(max_amount // candidate.price)
            if qty <= 0:
                return
            amount = qty * candidate.price
            overnight_total = self._risk_mgr.exposure_by_position_type(
                active, PositionType.CLOSE_BET
            )
            symbol_exposure = self._risk_mgr.symbol_exposure_by_position_type(
                active, symbol, PositionType.CLOSE_BET
            )
            approved, reason = self._risk_mgr.approve_entry(
                symbol=symbol,
                amount=amount,
                current_positions_count=len(active),
                total_exposure=overnight_total,
                market_strength_ok=True,
                position_type=PositionType.CLOSE_BET,
                symbol_exposure=symbol_exposure,
                overnight_total_exposure=overnight_total,
                kosdaq_change_pct=candidate.kosdaq_change_pct,
            )
            if not approved:
                logger.info("CLOSE_BET_ENTRY blocked risk: %s — %s", symbol, reason)
                return

            self._active_order_symbols.add(symbol)
            try:
                listing_market = listing_market_from_legacy(candidate.market)
                route = choose_routing(
                    self._venue_capability,
                    requested_policy=VenuePolicy.KRX_ONLY,
                    env=self._cfg.broker.env,
                    dry_run=self._cfg.strategy.dry_run,
                )
                req = OrderRequest(
                    symbol=symbol,
                    side="buy",
                    qty=qty,
                    price=candidate.price,
                    order_type="limit",
                    reason="close_bet_entry",
                    market=candidate.market,
                    position_type=PositionType.CLOSE_BET,
                    order_session="close_auction",
                    listing_market=listing_market,
                    execution_venue=ExecutionVenue.KRX,
                    preferred_venue=route.preferred_venue,
                    actual_venue=route.actual_venue,
                    venue_policy=route.venue_policy,
                    market_session=MarketSession.KRX_CLOSE_AUCTION,
                )
                order_no = await self._executor.submit(req)
                if not order_no:
                    await self._observe_live_guard_timeout("closebet_submit_failed")
                    return
                fill = await self._executor.wait_fill(order_no)
                if not fill:
                    await self._observe_live_guard_timeout("closebet_wait_fill_timeout")
                    return
                atr = self._signal_engine.get_atr(symbol) if self._signal_engine else 0.0
                self._position_mgr.on_fill_entry(
                    fill,
                    atr=atr,
                    position_type=PositionType.CLOSE_BET,
                    strategy_id=candidate.strategy_id or "close_bet_krx_only",
                    entry_session=MarketSession.KRX_CLOSE_AUCTION.value,
                    intended_exit_session="sor_next_open" if candidate.strategy_id == "close_bet_nxt_aware" else "next_open",
                    listing_market=listing_market,
                    preferred_venue=route.preferred_venue,
                    actual_venue=route.actual_venue,
                    venue_policy=route.venue_policy,
                    market_session=MarketSession.KRX_CLOSE_AUCTION,
                    krx_entry_price=fill.fill_price,
                    nxt_reference_price=float((candidate.nxt_metadata or {}).get("nxt_after_price") or 0),
                    venue_price_gap_at_entry=float((candidate.nxt_metadata or {}).get("venue_price_gap") or 0),
                    nxt_after_signal=str((candidate.nxt_metadata or {}).get("venue_gap_reason") or ""),
                )
                self._risk_mgr.record_entry(symbol, position_type=PositionType.CLOSE_BET)
                await self._save_position(symbol)

                slippage_exceeded, slippage = self._executor.check_slippage(
                    candidate.price, fill.fill_price, "buy"
                )
                if slippage_exceeded:
                    await self._observe_live_guard_slippage(slippage, symbol=symbol, side="buy")
                overnight_pct = (overnight_total + amount) / capital
                rec = self._journal.record_entry(
                    symbol=symbol,
                    order_no=order_no,
                    fill_price=fill.fill_price,
                    expected_price=candidate.price,
                    qty=fill.filled_qty,
                    commission=fill.commission,
                    slippage_pct=slippage,
                    score=candidate.score or 0.0,
                    exec_strength=candidate.exec_strength_30m,
                    ob_imbalance=0.0,
                    vwap_gap=0.0,
                    atr=atr,
                    vol_ratio=0.0,
                    market_kosdaq_pct=candidate.kosdaq_change_pct,
                    regime=self._regime_analyzer.current_regime.value,
                    position_type=PositionType.CLOSE_BET.value,
                    metadata={
                        "change_pct_at_entry": candidate.change_pct,
                        "exec_strength_30m": candidate.exec_strength_30m,
                        "vi_count_60m": candidate.vi_count_60m,
                        "kosdaq_at_entry": candidate.kosdaq_change_pct,
                        "trading_value_at_entry": candidate.trading_value,
                        "overnight_exposure_pct": overnight_pct,
                        "close_bet_grade": candidate.close_bet_grade,
                        "position_size_multiplier": size_multiplier,
                        "morning_exit_priority": candidate.morning_exit_priority,
                        "hold_extension_allowed": candidate.hold_extension_allowed,
                        "listing_market": listing_market.value,
                        "execution_venue": ExecutionVenue.KRX.value,
                        "preferred_venue": route.preferred_venue.value,
                        "actual_venue": route.actual_venue.value,
                        "venue_policy": route.venue_policy.value,
                        "market_session": MarketSession.KRX_CLOSE_AUCTION.value,
                        "krx_reference_price": fill.fill_price,
                        **(candidate.nxt_metadata or {}),
                    },
                )
                if self._store:
                    await self._store.log_trade({**rec.to_dict(), "type": "entry"})
                logger.info(
                    "CLOSE_BET_ENTRY: %s qty=%d price=%.0f score=%s grade=%s size_mult=%.2f exit_priority=%.1f overnight=%.2f%%",
                    symbol, fill.filled_qty, fill.fill_price,
                    candidate.score, candidate.close_bet_grade, size_multiplier,
                    candidate.morning_exit_priority, overnight_pct * 100,
                )
            finally:
                self._active_order_symbols.discard(symbol)

    async def _after_market_engine_loop(self) -> None:
        while _is_execution_active(self._status) and not self._kill_event.is_set():
            now = datetime.now().time()
            if self._status != BotStatus.RUNNING:
                await asyncio.sleep(60.0)
                continue
            if self._after_market_engine and AFTER_MARKET_START_TIME <= now <= AFTER_MARKET_END_TIME:
                await self._after_market_engine.run()
                if not self._daily_strategy_report_done:
                    try:
                        report = build_daily_strategy_report()
                        self._daily_strategy_report_done = True
                        logger.info(
                            "[DailyStrategyReport] generated strategies=%d promotion_state=%s",
                            len(report.get("strategy_stats", {})),
                            report.get("promotion_state_path", ""),
                        )
                    except Exception as exc:
                        logger.error("[DailyStrategyReport] generation failed: %s", exc)
                    # P2: CloseBet 별도 진단 (장 후 자동 실행)
                    try:
                        from .close_bet_diagnostics import build_close_bet_diagnostics
                        cb_report = build_close_bet_diagnostics()
                        logger.info(
                            "[CloseBetDiagnostics] trades=%d win_rate=%.1f%% promotion_ready=%s",
                            cb_report.get("total_trades", 0),
                            cb_report.get("win_rate", 0.0) * 100,
                            cb_report.get("promotion_ready", False),
                        )
                    except Exception as exc:
                        logger.debug("[CloseBetDiagnostics] failed: %s", exc)
            await asyncio.sleep(60.0)

    async def _take_morning_snapshot(self) -> None:
        """10:30 오전 강세 종목 스냅샷 — 점심 전략 백테스트 데이터 축적."""
        from .morning_snapshot import MorningSnapshotStore
        store = MorningSnapshotStore()
        regime_str = self._regime_analyzer.current_regime.value
        snapshots = []

        for symbol in list(self._watchlist):
            candidate = self._candidate_cache.get(symbol)
            st = self._signal_engine.get_symbol_state(symbol) if self._signal_engine else None
            if not candidate or not st:
                continue
            snap = store.build_snapshot(
                symbol=symbol,
                name=candidate.name,
                change_pct=candidate.change_pct,
                morning_high=st.morning_high if st.morning_high > 0 else st.last_price,
                price_now=st.last_price,
                trading_value=candidate.trading_value,
                exec_samples=list(st.morning_exec_samples),
                vol_ratio=st.last_vol_ratio,
                vwap=st.vwap.vwap,
                atr=st.atr.atr,
                regime=regime_str,
            )
            snapshots.append(snap)

        n_candidates = sum(1 for s in snapshots if s.is_lunch_candidate)
        logger.info(
            "[MorningSnapshot] %d snapshots saved, %d lunch candidates: %s",
            len(snapshots),
            n_candidates,
            [s.symbol for s in snapshots if s.is_lunch_candidate],
        )
        store.save_all(snapshots)

    async def _time_loop(self) -> None:
        # BUG-03 FIX: _is_active() — PAUSED 중에도 시간 감시 유지
        while _is_active(self._status) and not self._kill_event.is_set():
            now = datetime.now().time()
            if now >= FORCE_CLOSE_TIME:
                active_positions = (
                    self._position_mgr.active_positions()
                    if self._position_mgr else {}
                )
                n_active = len(active_positions)
                n_liquidation_required = len(
                    self._liquidation_required_positions(KillReason.FORCE_CLOSE_TIME)
                )
                if n_liquidation_required == 0:
                    if not self._force_close_skip_logged:
                        logger.info(
                            "Force close time reached. liquidation_required=0 active=%d — keeping service alive",
                            n_active,
                        )
                        self._force_close_skip_logged = True
                    await asyncio.sleep(1.0)
                    continue
                logger.warning(
                    "Force close time reached. positions=%d — triggering kill_switch",
                    n_active,
                )
                await self.kill_switch(KillReason.FORCE_CLOSE_TIME)
                return
            await asyncio.sleep(1.0)

    async def _dashboard_loop(self) -> None:
        """30초마다 운영 상태 스냅샷을 data/dashboard/에 기록.
        5분마다 logger 요약, 10분마다 buy_funnel_sentinel, 20분마다 exit/counterfactual sentinel.
        """
        _INTERVAL_SEC = 30
        _LOG_INTERVAL_SEC = 300
        _FUNNEL_INTERVAL_SEC = 600
        _SENTINEL_INTERVAL_SEC = 1200
        _last_log_ts = 0.0

        while _is_active(self._status) and not self._kill_event.is_set():
            await asyncio.sleep(_INTERVAL_SEC)
            try:
                now_ts = time.monotonic()
                snapshot = self._build_dashboard_snapshot()

                # JSONL 기록
                self._dashboard_log_path.mkdir(parents=True, exist_ok=True)
                log_file = self._dashboard_log_path / f"{date.today().isoformat()}.jsonl"
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(snapshot, ensure_ascii=False, default=str) + "\n")

                # 5분마다 콘솔 요약
                if now_ts - _last_log_ts >= _LOG_INTERVAL_SEC:
                    _last_log_ts = now_ts
                    top_reject = snapshot.get("top_reject_reasons", {})
                    top_reason = next(iter(top_reject), "none")
                    logger.warning(
                        "[Dashboard] regime=%s eq=%s orders=%d fills=%d "
                        "shadow=%d pnl=%.0f consecutive_loss=%d top_reject=%s",
                        snapshot.get("regime_score_label"),
                        snapshot.get("execution_quality_state"),
                        snapshot.get("live_order_count"),
                        snapshot.get("fill_count"),
                        snapshot.get("shadow_entry_count"),
                        snapshot.get("daily_pnl"),
                        snapshot.get("consecutive_losses"),
                        top_reason,
                    )

                # 10분마다 buy_funnel_sentinel
                if now_ts - self._dashboard_last_funnel_ts >= _FUNNEL_INTERVAL_SEC:
                    self._dashboard_last_funnel_ts = now_ts
                    try:
                        report = build_buy_funnel_sentinel_report()
                        rec = report.get("recommended_check", "normal")
                        if rec != "normal":
                            logger.warning("[FunnelSentinel] recommendation=%s terminal_blocker=%s",
                                           rec, report.get("top_terminal_blocker", ""))
                    except Exception as exc:
                        logger.debug("[FunnelSentinel] report failed: %s", exc)

                # 20분마다 exit sentinel + counterfactual (P1)
                if now_ts - self._dashboard_last_exit_sentinel_ts >= _SENTINEL_INTERVAL_SEC:
                    self._dashboard_last_exit_sentinel_ts = now_ts
                    try:
                        exit_report = build_holding_exit_sentinel_report()
                        if exit_report.get("strength_decay_candidate"):
                            logger.warning(
                                "[ExitSentinel] strength_decay_candidate detected open=%d",
                                exit_report.get("open_entry_count_estimate", 0),
                            )
                    except Exception as exc:
                        logger.debug("[ExitSentinel] report failed: %s", exc)

                if now_ts - self._dashboard_last_counterfactual_ts >= _SENTINEL_INTERVAL_SEC:
                    self._dashboard_last_counterfactual_ts = now_ts
                    try:
                        cf = build_missed_entry_counterfactual()
                        missed = cf.get("overall", {}).get("MISSED_WINNER", 0)
                        avoided = cf.get("overall", {}).get("AVOIDED_LOSER", 0)
                        if missed > 0 or avoided > 0:
                            logger.info(
                                "[Counterfactual] MISSED_WINNER=%d AVOIDED_LOSER=%d samples=%d",
                                missed, avoided, cf.get("sample_count", 0),
                            )
                    except Exception as exc:
                        logger.debug("[Counterfactual] report failed: %s", exc)

            except Exception as exc:
                logger.debug("[Dashboard] loop error: %s", exc)

    def _build_dashboard_snapshot(self) -> dict[str, Any]:
        """현재 봇 상태의 구조화된 스냅샷."""
        regime = self._current_runtime_regime()
        eq = self._current_execution_quality()
        qh = self._quote_health_snapshot
        risk = self._risk_mgr

        active_positions = self._position_mgr.active_positions() if self._position_mgr else {}
        n_pending_orders = len(self._executor.active_order_nos()) if self._executor else 0

        stale_ratio = 0.0
        if self._live_guard:
            stale_ratio = min(1.0, self._live_guard.state.stale_tick_repeats / max(1, self._live_guard.config.stale_tick_repeats))

        top_reject = dict(self._reject_reason_counter.most_common(5))
        terminal_blocker = next(iter(self._reject_reason_counter.most_common(1)), ("none",))[0]

        promotion_states: dict[str, str] = {}
        if self._promotion_gate:
            for strategy_key in list(self._last_strategy_signal_counts.keys()):
                try:
                    state_val = self._promotion_gate.state_for(strategy_key)
                    promotion_states[strategy_key] = state_val.value if state_val else "unknown"
                except Exception:
                    pass

        return {
            "event_type": "dashboard_snapshot",
            "timestamp": datetime.now().isoformat(),
            "bot_status": self._status.value,
            "kill_switch_state": self._status.value,
            # ── 후보/신호 ───────────────────────────────────────────────────
            "raw_candidate_count": self._scanner.last_raw_count if self._scanner else 0,
            "strategy_candidate_count": sum(self._last_strategy_signal_counts.values()),
            "signal_count_by_strategy": dict(self._last_strategy_signal_counts),
            "shadow_entry_count": sum(self._shadow_entry_counts.values()),
            # ── 주문/체결 ───────────────────────────────────────────────────
            "live_order_count": self._live_order_attempt_count,
            "fill_count": self._live_fill_count,
            "pending_orders": n_pending_orders,
            "active_positions": len(active_positions),
            # ── 거부 분석 ───────────────────────────────────────────────────
            "top_reject_reasons": top_reject,
            "terminal_blocker": terminal_blocker,
            # ── 실행 품질 ───────────────────────────────────────────────────
            "execution_quality_state": qh.latency_state.value if qh else "UNKNOWN",
            "execution_quality_score": round(eq.score, 4),
            "execution_quality_blocked": eq.blocked,
            "stale_tick_ratio": round(stale_ratio, 4),
            # ── 레짐 ────────────────────────────────────────────────────────
            "regime_score": round(regime.score, 3),
            "regime_score_label": regime.regime.value,
            # ── 전략 승격 ───────────────────────────────────────────────────
            "promotion_states": promotion_states,
            # ── 손익 ────────────────────────────────────────────────────────
            "daily_pnl": round(risk._state.realized_pnl, 0) if risk else 0.0,
            "unrealized_pnl": round(risk._state.unrealized_pnl, 0) if risk else 0.0,
            "consecutive_losses": risk._state.consecutive_losses if risk else 0,
        }

    async def _risk_loop(self) -> None:
        # BUG-03 FIX: _is_active() — PAUSED 중에도 리스크 상태 기록 유지
        while _is_active(self._status) and not self._kill_event.is_set():
            # BUG-25 FIX: 종목별 최신 체결가로 미실현 손익 계산
            if self._risk_mgr and self._position_mgr and self._signal_engine:
                total_unreal = 0.0
                for sym, pos in self._position_mgr.active_positions().items():
                    last_price = self._signal_engine.get_last_price(sym)
                    if last_price > 0 and pos.remaining_qty > 0:
                        total_unreal += (last_price - pos.avg_price) * pos.remaining_qty
                self._risk_mgr.update_unrealized(total_unreal)

            if self._risk_mgr:
                d = self._risk_mgr.to_dict()
                logger.info(
                    "[Risk] pnl=%.0f(%.2f%%) trades=%d W%d/L%d consec=%d halted=%s",
                    d["total_pnl"], d["total_pnl_pct"] * 100,
                    d["total_trades"], d["win_count"], d["loss_count"],
                    d["consecutive_losses"], d["is_halted"],
                )
                rd = self._regime_analyzer.to_dict()
                logger.info(
                    "[Regime] %s score=%.0f fb=%.0f%% vi=%d | candidate=%s",
                    rd["regime"], rd["score"],
                    rd["fake_breakout_ratio"] * 100,
                    rd["vi_count_30m"],
                    rd["candidate_regime"] or "-",
                )
                if self._store:
                    try:
                        await self._store.save_risk(d)
                        self._risk_store_errors = 0
                    except Exception as exc:
                        self._risk_store_errors += 1
                        logger.warning(
                            "StateStore save_risk failed (errors=%d/%d): %s",
                            self._risk_store_errors, MAX_RISK_STORE_ERRORS, exc,
                        )
                        # BUG-27 FIX: 연속 실패 임계치 초과 시에만 kill_switch (일시 장애 허용)
                        if self._risk_store_errors >= MAX_RISK_STORE_ERRORS:
                            await self.kill_switch(KillReason.STATE_SYNC_FAIL)
            await asyncio.sleep(10.0)

    async def _account_loop(self) -> None:
        """계좌 요약을 주기적으로 조회해 대시보드와 리스크 자본금을 갱신."""
        while _is_execution_active(self._status) and not self._kill_event.is_set():
            if not self._adapter:
                await asyncio.sleep(30.0)
                continue

            loop = asyncio.get_event_loop()
            try:
                bal = await asyncio.wait_for(loop.run_in_executor(
                    None,
                    lambda: self._adapter.inquire_balance(env_dv=self._cfg.broker.env),
                ), timeout=BALANCE_API_TIMEOUT_SEC)
                if bal.get("status") == "ok":
                    summary = bal.get("summary") or {}
                    deposit = float(summary.get("deposit") or 0)
                    total_eval = float(summary.get("total_eval") or 0)
                    purchase_amt = float(summary.get("purchase_amt") or 0)
                    eval_amt = float(summary.get("eval_amt") or 0)
                    profit_loss = float(summary.get("profit_loss") or 0)
                    profit_rate = float(summary.get("profit_rate") or 0)
                    holdings_count = len(bal.get("holdings") or [])

                    # KIS VTS는 total_eval이 비어 오는 경우가 있어 deposit을 fallback으로 사용.
                    account_capital = total_eval if total_eval > 0 else deposit
                    if self._risk_mgr and account_capital > 0:
                        self._risk_mgr.initialize_capital(account_capital)

                    logger.info(
                        "[Account] deposit=%.0f total_eval=%.0f purchase=%.0f eval=%.0f pnl=%.0f(%.2f%%) holdings=%d",
                        deposit, total_eval, purchase_amt, eval_amt,
                        profit_loss, profit_rate, holdings_count,
                    )
                    await self._reconcile_broker_positions(bal.get("holdings") or [])
                else:
                    logger.warning("[Account] balance query failed: %s", bal.get("error") or bal)
                    await self._record_reconcile_failure("balance_status_not_ok")
            except asyncio.TimeoutError:
                logger.warning("[Account] balance query timeout after %.1fs", BALANCE_API_TIMEOUT_SEC)
                await self._record_reconcile_failure("balance_timeout")
            except Exception as exc:
                logger.warning("[Account] balance query exception: %s", exc)
                await self._record_reconcile_failure("balance_exception")

            await asyncio.sleep(30.0)

    async def _record_reconcile_failure(self, reason: str) -> None:
        self._reconcile_failure_count += 1
        self._strategy_journal.record_order_event("broker_reconcile", {
            "status": "failure",
            "reason": reason,
            "failure_count": self._reconcile_failure_count,
        })
        if self._reconcile_failure_count >= 3:
            self._broker_reconcile_blocked = True
            self._emit_alert(
                kind="reconcile_failure",
                severity="critical",
                message=f"broker reconcile failure repeated: {reason}",
                payload={"failure_count": self._reconcile_failure_count},
            )
            await self.kill_switch(KillReason.STATE_SYNC_FAIL)

    async def _reconcile_broker_positions(self, holdings: list[dict[str, Any]]) -> None:
        if not self._position_mgr:
            return
        self._reconcile_failure_count = 0
        broker_qty: dict[str, int] = {}
        for holding in holdings:
            symbol = str(
                holding.get("symbol")
                or holding.get("pdno")
                or holding.get("code")
                or ""
            )
            qty = int(float(holding.get("qty") or holding.get("hldg_qty") or 0))
            if symbol and qty > 0:
                broker_qty[symbol] = qty

        local_positions = self._position_mgr.active_positions()
        mismatches: list[dict[str, Any]] = []
        for symbol, pos in local_positions.items():
            local_qty = int(pos.remaining_qty)
            remote_qty = int(broker_qty.get(symbol, 0))
            if local_qty != remote_qty:
                mismatches.append({
                    "symbol": symbol,
                    "local_qty": local_qty,
                    "broker_qty": remote_qty,
                    "type": "qty_mismatch" if remote_qty > 0 else "missing_broker_position",
                })
        for symbol, remote_qty in broker_qty.items():
            if symbol not in local_positions:
                mismatches.append({
                    "symbol": symbol,
                    "local_qty": 0,
                    "broker_qty": remote_qty,
                    "type": "unknown_broker_position",
                })

        if mismatches:
            self._reconcile_mismatch_count += 1
            self._broker_reconcile_blocked = True
            logger.critical("[Reconcile] broker/local mismatch: %s", mismatches)
            payload = {
                "status": "mismatch",
                "mismatch_count": self._reconcile_mismatch_count,
                "mismatches": mismatches,
            }
            self._strategy_journal.record_order_event("broker_reconcile", payload)
            self._emit_alert(
                kind="reconcile_mismatch",
                severity="critical",
                message=f"broker/local position mismatch x{self._reconcile_mismatch_count}",
                payload=payload,
            )
            if self._reconcile_mismatch_count >= 3:
                await self.kill_switch(KillReason.STATE_SYNC_FAIL)
            return

        if self._broker_reconcile_blocked:
            self._emit_alert(
                kind="reconcile_recovered",
                severity="info",
                message="broker/local positions reconciled",
                payload={},
            )
        self._broker_reconcile_blocked = False
        self._reconcile_mismatch_count = 0
        self._strategy_journal.record_order_event("broker_reconcile", {
            "status": "ok",
            "broker_positions": len(broker_qty),
            "local_positions": len(local_positions),
        })

    async def _strategy_schedule_loop(self) -> None:
        """대시보드용 시간대별 전략 상태를 주기적으로 로그에 남긴다."""
        while _is_execution_active(self._status) and not self._kill_event.is_set():
            try:
                snapshot = self._strategy_schedule_snapshot()
                logger.info(
                    "[StrategySchedule] current=%s label=%s active=%s reason=%s block_reason=%s "
                    "current_end=%s remaining_sec=%d next=%s next_label=%s next_start=%s "
                    "hard_no_trade=%s current_regime=%s candidate_regime=%s candidate_score=%.0f "
                    "candidate_age_sec=%d confirm_required_sec=%d confirm_remaining_sec=%d "
                    "last_valid_scan_age_sec=%d api_stall=%s signal_state=%s watchlist_count=%d "
                    "subscribed_count=%d position_count=%d order_count=%d top_block=%s "
                    "active_strategies=%s shadow_strategies=%s live_strategies=%s strategy_signals=%d",
                    snapshot["current"],
                    snapshot["label"],
                    str(snapshot["active"]).lower(),
                    snapshot["reason"],
                    snapshot["block_reason"],
                    snapshot["current_end"],
                    snapshot["remaining_sec"],
                    snapshot["next"],
                    snapshot["next_label"],
                    snapshot["next_start"],
                    str(snapshot["hard_no_trade"]).lower(),
                    snapshot["current_regime"],
                    snapshot["candidate_regime"] or "-",
                    snapshot["candidate_score"],
                    snapshot["candidate_age_sec"],
                    snapshot["confirm_required_sec"],
                    snapshot["confirm_remaining_sec"],
                    snapshot["last_valid_scan_age_sec"],
                    str(snapshot["api_stall"]).lower(),
                    snapshot["signal_state"],
                    snapshot["watchlist_count"],
                    snapshot["subscribed_count"],
                    snapshot["position_count"],
                    snapshot["order_count"],
                    snapshot["top_block"],
                    ",".join(snapshot.get("active_strategies") or []),
                    ",".join(snapshot.get("shadow_strategies") or []),
                    ",".join(snapshot.get("live_strategies") or []),
                    snapshot.get("strategy_signal_count", 0),
                )
                if snapshot["active"] and snapshot["signal_state"] == StrategyBlockReason.SIGNAL_WAITING.value:
                    self._log_no_entry_diagnosis(snapshot)
            except Exception as exc:
                logger.debug("[StrategySchedule] snapshot error: %s", exc)
            await asyncio.sleep(10.0)

    def _strategy_schedule_snapshot(self, now_dt: Optional[datetime] = None) -> dict[str, Any]:
        """현재 시간 기준 전략 타임라인 상태."""
        now_dt = now_dt or datetime.now()
        phase_state = self._phase_resolver.resolve(now_dt)
        current = phase_state.phase.value
        label = phase_state.label
        end_dt = phase_state.end_at
        next_name = phase_state.next_phase.value
        next_label = phase_state.next_phase.value
        next_dt = phase_state.next_at
        scheduled_active = phase_state.active
        schedule_reason = phase_state.reason

        rd = self._regime_analyzer.to_dict()
        active = scheduled_active and self._status == BotStatus.RUNNING
        reason = schedule_reason
        block_reason = StrategyBlockReason.OK.value if active else StrategyBlockReason.TIME_WINDOW_CLOSED.value
        if active and self._market_halted:
            active = False
            reason = "market_halted"
            block_reason = StrategyBlockReason.HARD_NO_TRADE.value
        if active and self._risk_mgr and self._risk_mgr.is_halted:
            active = False
            reason = "risk_halted"
            block_reason = StrategyBlockReason.RISK_HALTED.value
        if active and self._regime_analyzer.current_policy.regime == MarketRegime.NO_TRADE:
            active = False
            if rd.get("hard_no_trade"):
                reason = "hard_no_trade"
                block_reason = StrategyBlockReason.HARD_NO_TRADE.value
            elif rd.get("api_stall"):
                reason = "api_stall"
                block_reason = StrategyBlockReason.API_STALL.value
            elif rd.get("data_stale"):
                reason = "data_stale"
                block_reason = StrategyBlockReason.DATA_STALE.value
            elif rd.get("candidate_regime"):
                reason = "regime_confirming"
                block_reason = StrategyBlockReason.REGIME_CONFIRMING.value
            else:
                reason = "data_not_ready"
                block_reason = StrategyBlockReason.DATA_NOT_READY.value
        if scheduled_active and self._status != BotStatus.RUNNING:
            active = False
            reason = f"status_{self._status.value}"
            block_reason = reason

        signal_summary = self._signal_summary_snapshot()
        router_summary = self._strategy_router.last_summary
        runtime_regime = self._runtime_regime_snapshot
        execution_quality = self._execution_quality_snapshot
        if active and signal_summary["entry_signal"] == 0:
            signal_state = StrategyBlockReason.SIGNAL_WAITING.value
        else:
            signal_state = StrategyBlockReason.OK.value if active else block_reason

        remaining = max(0, int((end_dt - now_dt).total_seconds()))
        return {
            "current": current,
            "market_phase": phase_state.phase.value,
            "label": label,
            "active": active,
            "reason": reason,
            "block_reason": block_reason,
            "current_end": end_dt.strftime("%H:%M"),
            "remaining_sec": remaining,
            "next": next_name,
            "next_label": next_label,
            "next_start": next_dt.strftime("%m-%d_%H:%M") if next_dt.date() != now_dt.date() else next_dt.strftime("%H:%M"),
            "hard_no_trade": bool(rd.get("hard_no_trade")),
            "current_regime": rd.get("regime", "-"),
            "candidate_regime": rd.get("candidate_regime"),
            "candidate_score": float(rd.get("score", 0.0)),
            "runtime_regime": runtime_regime.regime.value if runtime_regime else "",
            "regime_score": runtime_regime.score if runtime_regime else 0.0,
            "regime_components": runtime_regime.components if runtime_regime else {},
            "hard_shift_triggered": bool(runtime_regime.hard_shift_triggered) if runtime_regime else False,
            "execution_quality_score": execution_quality.score if execution_quality else 0.0,
            "runtime_permissions": self._last_runtime_permission,
            "candidate_age_sec": int(rd.get("candidate_age_sec", 0)),
            "confirm_required_sec": int(rd.get("confirm_required_sec", 0)),
            "confirm_remaining_sec": int(rd.get("confirm_remaining_sec", 0)),
            "last_valid_scan_age_sec": int(self._scanner.last_valid_scan_age_sec if self._scanner else rd.get("last_valid_update_age_sec", 0)),
            "api_stall": bool(rd.get("api_stall")),
            "signal_state": signal_state,
            "watchlist_count": len(self._watchlist),
            "subscribed_count": len(self._ws_symbols),
            "position_count": len(self._position_mgr.active_positions()) if self._position_mgr else 0,
            "order_count": len(self._executor.active_order_nos()) if self._executor else 0,
            "signal_summary": signal_summary,
            "strategy_summary": router_summary,
            "active_strategies": router_summary.get("active_strategies", []),
            "shadow_strategies": router_summary.get("shadow_strategies", []),
            "live_strategies": router_summary.get("live_strategies", []),
            "strategy_signal_count": router_summary.get("signal_count", 0),
            "top_block": signal_summary.get("top_block", "none"),
        }

    def _signal_summary_snapshot(self) -> dict[str, Any]:
        if not self._signal_engine:
            return {
                "watchlist": len(self._watchlist),
                "ticks_recent": 0,
                "entry_signal": 0,
                "top_block": "signal_engine_not_ready",
            }
        policy = self._regime_analyzer.current_policy
        min_score = max(self._risk_mgr.adaptive_min_score(), policy.min_entry_score) if self._risk_mgr else policy.min_entry_score
        summary = self._signal_engine.signal_summary(self._watchlist, min_score)
        return summary

    def _log_no_entry_diagnosis(self, snapshot: dict[str, Any]) -> None:
        summary = snapshot.get("signal_summary") or {}
        logger.info(
            "[SignalSummary] watchlist=%d waiting_pullback=%d in_pullback=%d breakout_ready=%d "
            "score_below=%d exec_strength_below=%d vwap_not_ready=%d atr_missing=%d "
            "vol_ratio_missing=%d entry_signal=%d near_entry=%d best_score=%.1f "
            "avg_score_gap=%.1f avg_exec_strength_gap=%.1f avg_vol_ratio_gap=%.2f "
            "avg_pullback_gap_pct=%.2f top_missing_metric=%s top_block=%s",
            summary.get("watchlist", 0),
            summary.get("waiting_pullback", 0),
            summary.get("in_pullback", 0),
            summary.get("breakout_ready", 0),
            summary.get("score_below", 0),
            summary.get("exec_strength_below", 0),
            summary.get("vwap_not_ready", 0),
            summary.get("atr_missing", 0),
            summary.get("vol_ratio_missing", 0),
            summary.get("entry_signal", 0),
            summary.get("near_entry", 0),
            summary.get("best_score", 0.0),
            summary.get("avg_score_gap", 0.0),
            summary.get("avg_exec_strength_gap", 0.0),
            summary.get("avg_vol_ratio_gap", 0.0),
            summary.get("avg_pullback_gap_pct", 0.0),
            summary.get("top_missing_metric", "none"),
            summary.get("top_block", "none"),
        )
        logger.info(
            "[NoEntryDiagnosis] active=%s watchlist=%d subscribed=%d ticks_recent=%d "
            "entry_signals=%d top_block=%s waiting_pullback=%d breakout_not_confirmed=%d "
            "score_below=%d risk_rejected=0 order_count=%d best_score=%.1f "
            "avg_score_gap=%.1f avg_exec_strength_gap=%.1f avg_vol_ratio_gap=%.2f "
            "avg_pullback_gap_pct=%.2f top_missing_metric=%s near_entry=%d",
            str(snapshot.get("active")).lower(),
            snapshot.get("watchlist_count", 0),
            snapshot.get("subscribed_count", 0),
            summary.get("ticks_recent", 0),
            summary.get("entry_signal", 0),
            summary.get("top_block", "none"),
            summary.get("waiting_pullback", 0),
            summary.get("breakout_not_confirmed", 0),
            summary.get("score_below", 0),
            snapshot.get("order_count", 0),
            summary.get("best_score", 0.0),
            summary.get("avg_score_gap", 0.0),
            summary.get("avg_exec_strength_gap", 0.0),
            summary.get("avg_vol_ratio_gap", 0.0),
            summary.get("avg_pullback_gap_pct", 0.0),
            summary.get("top_missing_metric", "none"),
            summary.get("near_entry", 0),
        )
        for detail in (summary.get("details") or [])[:5]:
            logger.info(
                "[SignalState] symbol=%s phase=%s leader_rank=%s leader_score=%.1f "
                "score=%.1f score_threshold=%.1f score_gap=%.1f "
                "exec_strength=%.1f exec_strength_gap=%.1f vol_ratio=%.2f vol_ratio_gap=%.2f "
                "pullback_pct=%.3f pullback_gap_pct=%.2f breakout_ticks_missing=%d "
                "vwap_warmup_ticks_missing=%d reject_reason=%s",
                detail.get("symbol", "-"),
                detail.get("phase", "-"),
                detail.get("leader_rank", 999),
                detail.get("leader_score", 0.0),
                detail.get("score", 0.0),
                detail.get("score_threshold", 0.0),
                detail.get("score_gap", 0.0),
                detail.get("exec_strength", 0.0),
                detail.get("exec_strength_gap", 0.0),
                detail.get("vol_ratio", 0.0),
                detail.get("vol_ratio_gap", 0.0),
                detail.get("pullback_pct", 0.0),
                detail.get("pullback_gap_pct", 0.0),
                detail.get("breakout_ticks_missing", 0),
                detail.get("vwap_warmup_ticks_missing", 0),
                detail.get("reject_reason", "-"),
            )

    async def _wait_for_kill(self) -> None:
        await self._kill_event.wait()

    # ═══════════════════════════════════════════════════════════════════════════
    # 헬퍼
    # ═══════════════════════════════════════════════════════════════════════════

    async def _save_position(self, symbol: str) -> None:
        if not self._store or not self._position_mgr:
            return
        pos = self._position_mgr.get_position(symbol)
        if not pos:
            return
        try:
            await self._store.save_position(symbol, {
                "symbol":                   symbol,
                "avg_price":                pos.avg_price,
                "entry_price":              pos.entry_price,       # BUG-10 FIX
                "remaining_qty":            pos.remaining_qty,
                "total_qty":                pos.total_qty,
                "hard_stop":                pos.hard_stop,
                "trailing_high":            pos.trailing_high,
                "trailing_stop":            pos.trailing_stop,
                "break_even_stop":          pos.break_even_stop,
                "atr_at_entry":             pos.atr_at_entry,
                "phase":                    pos.phase.value,       # BUG-11 FIX
                "realized_pnl":             pos.realized_pnl,      # BUG-13 FIX
                "exit_1_triggered":         pos.exit_1_triggered,  # BUG-12 FIX
                "exit_2_triggered":         pos.exit_2_triggered,  # BUG-12 FIX
                "market":                   pos.market,
                "snapshot_version":         SNAPSHOT_VERSION,
                # ── 포지션 목적 분류 (익일 복구 / 타입 구분 필수) ──────────
                "position_type":            pos.position_type.value,
                "opened_at":                pos.opened_at.isoformat(),
                "strategy_id":              pos.strategy_id,
                "entry_session":            pos.entry_session,
                "intended_exit_session":    pos.intended_exit_session,
                "listing_market":           pos.listing_market.value,
                "execution_venue":          pos.execution_venue.value,
                "preferred_venue":          pos.preferred_venue.value,
                "actual_venue":             pos.actual_venue.value,
                "venue_policy":             pos.venue_policy.value,
                "market_session":           pos.market_session.value,
                "krx_entry_price":          pos.krx_entry_price,
                "nxt_reference_price":      pos.nxt_reference_price,
                "venue_price_gap_at_entry": pos.venue_price_gap_at_entry,
                "nxt_after_signal":         pos.nxt_after_signal,
                "nxt_pre_signal":           pos.nxt_pre_signal,
            }, ttl=ttl_for(pos.position_type))
            self._pos_store_errors = 0
        except Exception as exc:
            self._pos_store_errors += 1
            logger.error(
                "save_position failed %s (errors=%d/%d): %s",
                symbol, self._pos_store_errors, MAX_POS_STORE_ERRORS, exc,
            )
            if self._pos_store_errors >= MAX_POS_STORE_ERRORS:
                await self.kill_switch(KillReason.STATE_SYNC_FAIL)

    async def _calc_entry_qty(self, symbol: str, price: float) -> int:
        if price <= 0:
            return 0
        if self._cfg.strategy.dry_run:
            return 10
        buyable = await self._executor.get_buyable_qty(symbol, price)
        if self._risk_mgr and self._risk_mgr.state.capital > 0:
            max_amt = self._risk_mgr.state.capital * self._cfg.strategy.max_position_pct
            return max(0, min(buyable, int(max_amt / price)))
        return min(buyable, 10)

    # ═══════════════════════════════════════════════════════════════════════════
    # 외부 상태 조회
    # ═══════════════════════════════════════════════════════════════════════════

    def status_dict(self) -> dict:
        positions = {}
        if self._position_mgr:
            for sym, pos in self._position_mgr.active_positions().items():
                positions[sym] = {
                    "phase":           pos.phase.value,
                    "avg_price":       pos.avg_price,
                    "remaining_qty":   pos.remaining_qty,
                    "hard_stop":       pos.hard_stop,
                    "trailing_stop":   pos.trailing_stop,
                    "break_even_stop": pos.break_even_stop,
                    "realized_pnl":    pos.realized_pnl,
                }
        stopping_elapsed = (
            round(time.monotonic() - self._stopping_ts, 1)
            if self._stopping_ts > 0 else 0.0
        )
        return {
            "status":           self._status.value,
            "kill_reason":      self._kill_reason,
            "stopping_elapsed": stopping_elapsed,
            "watchlist":        sorted(self._watchlist),
            "positions":        positions,
            "pending_orders":   self._executor.active_order_nos() if self._executor else [],
            "risk":             self._risk_mgr.to_dict() if self._risk_mgr else {},
            "journal":          self._journal.summary(),
            "ws_reconnects":    self._ws_reconnect_count,
            "last_tick_ago":    round(time.monotonic() - self._last_tick_ts, 1)
                                if self._last_tick_ts > 0 else -1,
        }


# ── 싱글턴 ────────────────────────────────────────────────────────────────────

_bot: Optional[ScalpingBot] = None
_bot_task: Optional[asyncio.Task] = None


def get_bot() -> Optional[ScalpingBot]:
    return _bot


async def start_bot(
    symbols: list[str],
    config: Optional[ScalpingBotConfig] = None,
) -> ScalpingBot:
    global _bot, _bot_task
    if _bot and _bot._status == BotStatus.RUNNING:
        return _bot
    _bot = ScalpingBot(config)
    loop = asyncio.get_event_loop()
    _bot_task = loop.create_task(_bot.run(symbols))
    return _bot


async def stop_bot() -> None:
    global _bot, _bot_task
    if _bot:
        await _bot.kill_switch(KillReason.MANUAL)
        # BUG-34 FIX: kill_event 대기 — 청산 완료 후 태스크 취소 (30s + 5s grace)
        try:
            await asyncio.wait_for(_bot._kill_event.wait(), timeout=_STOPPING_TIMEOUT_SECS + 5.0)
        except asyncio.TimeoutError:
            logger.warning("stop_bot: kill_event timeout — forcing task cancel")
    if _bot_task:
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            pass
    _bot = None
    _bot_task = None
