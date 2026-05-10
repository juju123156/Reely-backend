from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import time as dtime
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.trading.scalping.events import FillEvent, OrderRequest, SignalEvent, TickEvent
from src.trading.scalping.order_executor import OrderExecutor
import src.trading.scalping.order_executor as order_executor_module
from src.trading.scalping.orderbook_pressure import OrderbookPressureFilter, snapshot_from_tick
from src.trading.scalping.position_manager import PositionManager
from src.trading.scalping.regime_runtime import (
    ExecutionQualityGate,
    ExecutionQualityInputs,
    LatencyState,
    QuoteHealthMonitor,
    RegimeSnapshot,
    RuntimePermissionGate,
    RuntimeRegime,
)
from src.trading.scalping.risk_manager import RiskManager
from src.trading.scalping.strategy_promotion import PromotionState

from .fake_broker import FakeBroker
from .fake_clock import FakeClock


@dataclass
class FakeJournal:
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, event_type: str, **payload: Any) -> dict[str, Any]:
        row = {"event_type": event_type, **payload}
        self.events.append(row)
        return row

    def count(self, event_type: str) -> int:
        return sum(1 for event in self.events if event["event_type"] == event_type)

    def latest(self, event_type: str) -> dict[str, Any]:
        for event in reversed(self.events):
            if event["event_type"] == event_type:
                return event
        return {}

    def reasons(self) -> list[str]:
        return [str(e.get("reject_reason") or e.get("reason") or "") for e in self.events]


@dataclass
class ScenarioConfig:
    symbol: str = "TEST001"
    strategy: str = "leader_only_shallow_pullback"
    promotion_state: PromotionState = PromotionState.SMALL_LIVE
    regime: RuntimeRegime = RuntimeRegime.STRONG
    capital: float = 10_000_000
    qty: int = 100
    atr: float = 300
    score: float = 80
    leader_score: float = 75
    vwap_gap: float = 0.002
    exec_strength: float = 130
    orderbook_age_sec: float = 0.2
    tick_age_sec: float = 0.1
    market_phase: str = "MORNING_SCALP"
    daily_pnl: float = 0.0
    consecutive_losses: int = 0


class FakePositionStore:
    def __init__(self, broker: FakeBroker, position_manager: PositionManager) -> None:
        self.broker = broker
        self.position_manager = position_manager

    def reconcile(self, symbol: str) -> tuple[bool, dict[str, int]]:
        local = self.position_manager.get_position(symbol)
        local_qty = local.remaining_qty if local else 0
        broker_qty = self.broker.fetch_positions().get(symbol, 0)
        return local_qty == broker_qty, {"local_qty": local_qty, "broker_qty": broker_qty}


class ScalpingE2EHarness:
    def __init__(self, tmp_path: Path, config: ScenarioConfig | None = None) -> None:
        self.tmp_path = tmp_path
        self.config = config or ScenarioConfig()
        self.clock = FakeClock.at("09:20:00")
        self.journal = FakeJournal()
        self.broker = FakeBroker()
        order_executor_module.NO_ORDER_AFTER = dtime(23, 59, 59)
        self.executor = OrderExecutor(self.broker, dry_run=False, dry_run_order=True)
        self.positions = PositionManager()
        self.risk = RiskManager(capital=self.config.capital)
        self.risk.state.realized_pnl = self.config.daily_pnl
        self.risk.state.consecutive_losses = self.config.consecutive_losses
        self.quote_health = QuoteHealthMonitor()
        self.execution_gate = ExecutionQualityGate()
        self.runtime_gate = RuntimePermissionGate()
        self.orderbook_gate = OrderbookPressureFilter()
        self.store = FakePositionStore(self.broker, self.positions)
        self.record_id = f"e2e:{self.config.symbol}:{self.config.strategy}"

    def make_signal(self, tick: TickEvent) -> SignalEvent:
        return SignalEvent(
            symbol=tick.symbol,
            score=self.config.score,
            action="enter_now",
            reason=self.config.strategy,
            exec_strength=self.config.exec_strength,
            ob_imbalance=1.2,
            vwap_gap=self.config.vwap_gap,
            atr=self.config.atr,
            price=tick.price,
            ts=self.clock.now,
        )

    def _regime_snapshot(self) -> RegimeSnapshot:
        score = {
            RuntimeRegime.WEAK: 35.0,
            RuntimeRegime.CHOPPY: 35.0,
            RuntimeRegime.NORMAL: 55.0,
            RuntimeRegime.STRONG: 75.0,
            RuntimeRegime.TRENDING: 85.0,
            RuntimeRegime.NO_TRADE: 10.0,
            RuntimeRegime.CONFIRMING: 10.0,
        }[self.config.regime]
        return RegimeSnapshot(self.config.regime, score, {}, self.clock.now.timestamp())

    def _execution_snapshot(self, tick: TickEvent):
        qh = self.quote_health.classify(
            quote_age_ms=self.config.orderbook_age_sec * 1000,
            tick_age_ms=self.config.tick_age_sec * 1000,
            orderbook_age_sec=self.config.orderbook_age_sec,
            spread_pct=(tick.ask1_price - tick.bid1_price) / tick.price if tick.price else 0,
            top_of_book_missing=tick.bid1_price <= 0 or tick.ask1_price <= 0,
            depth_levels_available=tick.depth_levels_available,
        )
        eq = self.execution_gate.score(
            ExecutionQualityInputs(
                quote_age_ms=qh.quote_age_ms,
                websocket_gap_ms=qh.tick_age_ms,
                orderbook_collapse_ratio=1.0 if qh.latency_state == LatencyState.DANGER else 0.0,
                top_of_book_missing=qh.top_of_book_missing,
                depth_levels_available=qh.depth_levels_available,
            )
        )
        self.journal.emit("quote_health_snapshot", record_id=self.record_id, **qh.to_dict())
        self.journal.emit("latency_state", record_id=self.record_id, latency_state=qh.latency_state.value)
        self.journal.emit("execution_quality_snapshot", record_id=self.record_id, **eq.to_dict())
        return qh, eq

    async def enter(self, tick: TickEvent) -> FillEvent | None:
        self.executor.update_market_snapshot(tick)
        signal = self.make_signal(tick)
        self.journal.emit("pipeline_event", record_id=self.record_id, stage="candidate_detected", symbol=tick.symbol)
        self.journal.emit("pipeline_event", record_id=self.record_id, stage="route_candidate", symbol=tick.symbol, strategy=self.config.strategy)
        self.journal.emit("signal_generated", record_id=self.record_id, symbol=tick.symbol, strategy=self.config.strategy, score=signal.score)
        self.journal.emit("pipeline_event", record_id=self.record_id, stage="signal_generated", symbol=tick.symbol, strategy=self.config.strategy)
        self.journal.emit("shadow_entry_created", record_id=self.record_id, symbol=tick.symbol, strategy=self.config.strategy)

        if self.config.promotion_state not in {PromotionState.SMALL_LIVE, PromotionState.NORMAL_LIVE}:
            self.journal.emit("gatekeeper_snapshot", record_id=self.record_id, final_decision="shadow_only", terminal_blocker="promotion_gate_shadow_only")
            self.journal.emit("strategy_reject", record_id=self.record_id, reject_reason="promotion_gate_shadow_only")
            return None

        qh, eq = self._execution_snapshot(tick)
        runtime = self.runtime_gate.evaluate(
            strategy=self.config.strategy,
            promotion_state=self.config.promotion_state,
            regime=self._regime_snapshot(),
            execution_quality=eq,
            market_phase=self.config.market_phase,
            last_tick_age_sec=self.config.tick_age_sec,
            stale_feature_age_sec=self.config.tick_age_sec,
            metrics={"leader_score": self.config.leader_score},
        )
        self.journal.emit("runtime_permission", record_id=self.record_id, **runtime.to_dict())
        if not runtime.allowed:
            self.journal.emit("gatekeeper_snapshot", record_id=self.record_id, final_decision="block", terminal_blocker=runtime.blocked_reason)
            self.journal.emit("strategy_reject", record_id=self.record_id, reject_reason=runtime.blocked_reason)
            return None
        if qh.latency_state == LatencyState.DANGER or eq.blocked:
            reason = qh.blocked_reason or eq.blocked_reason
            self.journal.emit("gatekeeper_snapshot", record_id=self.record_id, final_decision="block", terminal_blocker=reason)
            self.journal.emit("strategy_reject", record_id=self.record_id, reject_reason=reason)
            return None

        pressure = self.orderbook_gate.evaluate(snapshot_from_tick(tick), required_qty=self.config.qty)
        self.journal.emit("microprice_snapshot", record_id=self.record_id, **pressure.to_dict())
        if pressure.blocked:
            self.journal.emit("strategy_reject", record_id=self.record_id, reject_reason=pressure.block_reason)
            return None

        approved, reason = self.risk.approve_entry(
            symbol=tick.symbol,
            amount=tick.ask1_price * self.config.qty,
            current_positions_count=len(self.positions.active_positions()),
            total_exposure=0,
            strategy_name=self.config.strategy,
            max_daily_trades_override=runtime.max_daily_trades,
            max_trades_per_strategy_override=runtime.max_trades_per_strategy,
        )
        if not approved:
            self.journal.emit("strategy_reject", record_id=self.record_id, reject_reason=reason)
            self.journal.emit("gatekeeper_snapshot", record_id=self.record_id, final_decision="block", terminal_blocker="risk_manager")
            return None

        req = OrderRequest(tick.symbol, "buy", self.config.qty, tick.ask1_price, "limit", "entry_1", ref_id=self.record_id)
        self.journal.emit("order_state_event", record_id=self.record_id, state="submitted", side="buy")
        self.journal.emit("live_order_attempt", record_id=self.record_id, symbol=tick.symbol, side="buy")
        order_no = await self.executor.submit(req)
        if not order_no:
            self.journal.emit("order_state_event", record_id=self.record_id, state="rejected", side="buy")
            return None
        fill = await self.executor.wait_fill(order_no, timeout=2.0)
        record = self.executor.get_record(order_no)
        if not fill:
            self.journal.emit("order_state_event", record_id=self.record_id, state="timeout", side="buy")
            self.journal.emit("signal_expired", record_id=self.record_id)
            return None
        self.journal.emit("order_state_event", record_id=self.record_id, state=record.status.value if record else "filled", side="buy", remaining_qty=record.remaining_qty if record else 0)
        self.journal.emit("fill_event", record_id=self.record_id, side="buy", qty=fill.filled_qty, price=fill.fill_price)
        self.broker.apply_fill(tick.symbol, "buy", fill.filled_qty)
        self.positions.on_fill_entry(fill, self.config.atr, strategy_id=self.config.strategy)
        self.risk.record_entry(tick.symbol, strategy_name=self.config.strategy)
        self.journal.emit("position_event", record_id=self.record_id, state="opened", qty=fill.filled_qty)
        ok, payload = self.store.reconcile(tick.symbol)
        self.journal.emit("broker_reconcile_event", record_id=self.record_id, ok=ok, **payload)
        return fill

    async def exit_if_triggered(self, tick: TickEvent) -> FillEvent | None:
        self.executor.update_market_snapshot(tick)
        req = self.positions.check_exits(
            tick.symbol,
            tick,
            exec_strength=self.config.exec_strength,
            ob_imbalance=1.2,
            vwap=10_000,
            now_time=self.clock.time,
        )
        if not req:
            return None
        self.journal.emit("exit_signal", record_id=self.record_id, reason=req.reason)
        self.journal.emit("order_state_event", record_id=self.record_id, state="submitted", side="sell")
        order_no = await self.executor.submit(req, emergency=True)
        if not order_no:
            self.journal.emit("order_state_event", record_id=self.record_id, state="rejected", side="sell")
            return None
        fill = await self.executor.wait_fill(order_no, timeout=2.0)
        if not fill:
            self.journal.emit("order_state_event", record_id=self.record_id, state="timeout", side="sell")
            return None
        pos = self.positions.on_fill_exit(fill)
        realized = pos.realized_pnl if pos else 0.0
        self.risk.record_trade(tick.symbol, realized, fill.commission + fill.tax)
        self.broker.apply_fill(tick.symbol, "sell", fill.filled_qty)
        self.journal.emit("order_state_event", record_id=self.record_id, state="filled", side="sell")
        self.journal.emit("fill_event", record_id=self.record_id, side="sell", qty=fill.filled_qty, price=fill.fill_price)
        self.journal.emit("position_event", record_id=self.record_id, state="closed" if not self.positions.active_positions() else "partial")
        self.journal.emit("pnl_event", record_id=self.record_id, pnl=realized)
        self.journal.emit("live_trade_result", record_id=self.record_id, pnl=realized)
        ok, payload = self.store.reconcile(tick.symbol)
        self.journal.emit("broker_reconcile_event", record_id=self.record_id, ok=ok, **payload)
        return fill

    async def partial_then_cancel(self, tick: TickEvent) -> None:
        self.executor.update_market_snapshot(tick)
        req = OrderRequest(tick.symbol, "buy", self.config.qty, tick.ask1_price, "limit", "entry_1", ref_id=self.record_id)
        order_no = await self.executor.submit(req)
        assert order_no
        fill = await self.executor.wait_fill(order_no, timeout=2.0)
        assert fill
        record = self.executor.get_record(order_no)
        self.broker.apply_fill(tick.symbol, "buy", fill.filled_qty)
        self.positions.on_fill_entry(fill, self.config.atr, strategy_id=self.config.strategy)
        self.journal.emit("order_state_event", record_id=self.record_id, state=record.status.value if record else "partially_filled", remaining_qty=record.remaining_qty if record else 0)
        await self.executor.cancel_pending(order_no)
        record = self.executor.get_record(order_no)
        self.journal.emit("order_state_event", record_id=self.record_id, state=record.status.value if record else "canceled", remaining_qty=record.remaining_qty if record else 0)
        ok, payload = self.store.reconcile(tick.symbol)
        self.journal.emit("broker_reconcile_event", record_id=self.record_id, ok=ok, **payload)

    async def timeout_entry(self, tick: TickEvent) -> None:
        self.executor.update_market_snapshot(tick)
        req = OrderRequest(tick.symbol, "buy", self.config.qty, tick.bid1_price, "limit", "entry_1", ref_id=self.record_id)
        order_no = await self.executor.submit(req)
        assert order_no
        fill = await self.executor.wait_fill(order_no, timeout=2.0)
        assert fill is None
        record = self.executor.get_record(order_no)
        self.journal.emit("order_state_event", record_id=self.record_id, state="timeout", side="buy")
        self.journal.emit("order_state_event", record_id=self.record_id, state=record.status.value if record else "canceled", side="buy")
        self.journal.emit("signal_expired", record_id=self.record_id)

    def age_position(self, seconds: int) -> None:
        pos = self.positions.get_position(self.config.symbol)
        if pos:
            pos.opened_at = pos.opened_at - timedelta(seconds=seconds)

    async def force_close(self, tick: TickEvent) -> FillEvent | None:
        self.clock = FakeClock.at("15:20:00")
        return await self.exit_if_triggered(tick)

    def write_daily_report(self) -> dict[str, Any]:
        pnl = sum(float(e.get("pnl", 0.0) or 0.0) for e in self.journal.events if e["event_type"] == "pnl_event")
        report = {
            "record_id": self.record_id,
            "pnl": pnl,
            "orders": self.journal.count("live_order_attempt"),
            "fills": self.journal.count("fill_event"),
            "pipeline_events": self.journal.count("pipeline_event"),
        }
        self.journal.emit("daily_strategy_report", **report)
        return report
