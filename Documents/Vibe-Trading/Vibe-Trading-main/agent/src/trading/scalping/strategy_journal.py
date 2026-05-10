"""JSONL persistence for strategy diagnostics."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .pipeline_events import PipelineEventLogger, event_from_diagnostic, make_record_id
from .strategy_types import StrategyCandidate, StrategySignal


class StrategySignalJournal:
    def __init__(
        self,
        shadow_dir: str | Path = "data/strategy_shadow",
        live_dir: str | Path = "data/strategy_live",
    ) -> None:
        self._shadow_dir = Path(shadow_dir)
        self._live_dir = Path(live_dir)
        self._pipeline = PipelineEventLogger()
        self._record_ids: dict[tuple[str, str], str] = {}

    def record_id_for(self, symbol: str, strategy: str = "") -> str:
        key = (str(symbol or "unknown"), str(strategy or "unknown"))
        record_id = self._record_ids.get(key)
        if not record_id:
            record_id = make_record_id(key[0], key[1])
            self._record_ids[key] = record_id
        return record_id

    def record_signal(self, signal: StrategySignal, mode: str, event_type: str = "strategy_signal") -> None:
        base = self._live_dir if mode == "live" else self._shadow_dir
        path = base / f"{date.today().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = asdict(signal)
        record_id = self.record_id_for(signal.symbol, signal.strategy_name)
        payload.update({
            "ts": datetime.now().isoformat(),
            "record_id": record_id,
            "strategy": signal.strategy_name,
            "mode": mode,
            "event_type": event_type,
            "entry_triggered": signal.entry_price is not None,
            "entry_price": signal.entry_price,
            "reject_reason": signal.reason if signal.entry_price is None else None,
            "expected_edge_pct": signal.expected_edge_pct,
        })
        payload["position_type"] = signal.position_type.value
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self.record_pipeline_event(
            stage="signal_generated",
            symbol=signal.symbol,
            strategy=signal.strategy_name,
            accepted=signal.entry_price is not None,
            reject_reason=signal.reason if signal.entry_price is None else "",
            payload=payload,
            record_id=record_id,
        )

    def record_reject(
        self,
        *,
        symbol: str,
        name: str = "",
        strategy: str,
        stage: str,
        reject_reason: str,
        metrics: dict | None = None,
        accepted: bool = False,
        market_regime: str = "",
        schedule: str = "",
        tick_age_sec: float | None = None,
        feature_readiness: dict | None = None,
    ) -> None:
        record_id = self.record_id_for(symbol, strategy)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "record_id": record_id,
            "symbol": symbol,
            "name": name,
            "strategy": strategy,
            "stage": stage,
            "accepted": accepted,
            "reject_reason": reject_reason,
            "metrics": metrics or {},
            "active_market_regime": market_regime,
            "active_schedule": schedule,
            "tick_age_sec": tick_age_sec,
            "feature_readiness": feature_readiness or {},
        }
        self._append_diagnostic("strategy_reject", payload)
        self.record_pipeline_event(
            stage=stage,
            symbol=symbol,
            name=name,
            strategy=strategy,
            accepted=accepted,
            reject_reason=reject_reason,
            terminal_blocker=reject_reason,
            payload=payload,
            record_id=record_id,
        )

    def record_route_summary(
        self,
        *,
        raw_scan_count: int,
        after_etf_filter_count: int,
        after_liquidity_filter_count: int,
        after_regime_filter_count: int,
        candidates: list[StrategyCandidate],
        strategy_signal_count_by_strategy: dict[str, int] | None = None,
        top_rejected_reasons: dict[str, int] | None = None,
        top_near_miss_symbols: list[dict] | None = None,
        active_strategies: list[str] | None = None,
        current_schedule: str = "",
        market_regime: str = "",
        shadow_entry_count_by_strategy: dict[str, int] | None = None,
        live_order_attempt_count: int = 0,
        fill_count: int = 0,
        stale_feature_ratio: float = 0.0,
    ) -> None:
        by_strategy: dict[str, int] = {}
        for candidate in candidates:
            by_strategy[candidate.strategy_name] = by_strategy.get(candidate.strategy_name, 0) + 1
        self._append_diagnostic("route_summary", {
            "timestamp": datetime.now().isoformat(),
            "raw_scan_count": raw_scan_count,
            "after_etf_filter_count": after_etf_filter_count,
            "after_liquidity_filter_count": after_liquidity_filter_count,
            "after_regime_filter_count": after_regime_filter_count,
            "strategy_candidate_count_by_strategy": by_strategy,
            "strategy_signal_count_by_strategy": strategy_signal_count_by_strategy or {},
            "shadow_entry_count_by_strategy": shadow_entry_count_by_strategy or {},
            "live_order_attempt_count": live_order_attempt_count,
            "fill_count": fill_count,
            "top_rejected_reasons": top_rejected_reasons or {},
            "top_near_miss_symbols": top_near_miss_symbols or [],
            "stale_feature_ratio": stale_feature_ratio,
            "active_strategies": active_strategies or [],
            "current_schedule": current_schedule,
            "market_regime": market_regime,
        })
        for candidate in candidates[:100]:
            self.record_pipeline_event(
                stage="route_candidate",
                symbol=candidate.symbol,
                strategy=candidate.strategy_name,
                accepted=True,
                payload={
                    "symbol": candidate.symbol,
                    "strategy": candidate.strategy_name,
                    "stage": "route_candidate",
                    "accepted": True,
                    "metrics": candidate.metrics,
                    "market_regime": market_regime,
                    "current_schedule": current_schedule,
                    "reason": candidate.reason,
                },
            )

    def record_signal_snapshot(
        self,
        *,
        symbol: str,
        name: str = "",
        snapshot: dict,
        tick_count: int = 0,
        last_tick_age_sec: float | None = None,
        stale_feature_age_sec: float | None = None,
        market_regime: str = "",
        schedule: str = "",
    ) -> None:
        self._append_diagnostic("signal_snapshot", {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "name": name,
            "snapshot": snapshot,
            "tick_count": tick_count,
            "last_tick_age_sec": last_tick_age_sec,
            "stale_feature_age_sec": stale_feature_age_sec,
            "vwap_ready": bool(snapshot.get("vwap_ready")),
            "atr_ready": bool(snapshot.get("atr_ready")),
            "exec_strength_samples": snapshot.get("exec_strength_samples", 0),
            "active_market_regime": market_regime,
            "active_schedule": schedule,
        })
        self._append_diagnostic("feature_freshness", {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "name": name,
            "tick_count": tick_count,
            "last_tick_age_sec": last_tick_age_sec,
            "stale_feature_age_sec": stale_feature_age_sec,
            "vwap_ready": bool(snapshot.get("vwap_ready")),
            "atr_ready": bool(snapshot.get("atr_ready")),
            "exec_strength_samples": snapshot.get("exec_strength_samples", 0),
            "active_market_regime": market_regime,
            "active_schedule": schedule,
        })

    def record_order_event(self, event_type: str, payload: dict) -> None:
        allowed = {
            "live_order_attempt",
            "live_order_fill",
            "live_order_timeout",
            "slippage_report",
            "closebet_near_miss",
            "shadow_trade_result",
            "daily_strategy_report",
            "regime_snapshot",
            "runtime_permission",
            "execution_quality",
            "microprice_snapshot",
            "depth_fill_estimate",
            "broker_reconcile",
            "orderbook_snapshot",
            "tick_merge_result",
            "pipeline_event",
            "gatekeeper_snapshot",
            "quote_health_snapshot",
            "latency_state",
            "entry_policy_reject",
            "missed_entry_counterfactual",
            "blocker_outcome_summary",
            "orderbook_stability_snapshot",
            "buy_funnel_sentinel_report",
            "holding_exit_sentinel_report",
            "candidate_provenance_snapshot",
            "expected_edge_snapshot",
            "expected_vs_actual_edge",
            "runner_decision",
            "exit_profile_selected",
        }
        if event_type not in allowed:
            raise ValueError(f"unsupported order diagnostic event_type={event_type}")
        row = {"timestamp": datetime.now().isoformat(), **payload}
        self._append_diagnostic(event_type, row)
        if event_type in {
            "live_order_attempt",
            "live_order_fill",
            "live_order_timeout",
            "entry_policy_reject",
            "gatekeeper_snapshot",
        }:
            symbol = str(row.get("symbol") or "")
            strategy = str(row.get("strategy_id") or row.get("strategy") or "current_strategy")
            self.record_pipeline_event(
                stage=event_type,
                symbol=symbol,
                strategy=strategy,
                accepted=event_type == "live_order_fill",
                reject_reason=str(row.get("reject_reason") or ""),
                payload=row,
                record_id=str(row.get("record_id") or row.get("signal_event_id") or self.record_id_for(symbol, strategy)),
            )

    def record_pipeline_event(
        self,
        *,
        stage: str,
        symbol: str,
        strategy: str = "",
        name: str = "",
        accepted: bool = False,
        reject_reason: str = "",
        terminal_blocker: str = "",
        payload: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        rid = record_id or str(payload.get("record_id") or self.record_id_for(symbol, strategy))
        event = event_from_diagnostic(
            record_id=rid,
            stage=stage,
            payload={
                **payload,
                "symbol": symbol,
                "name": name or payload.get("name", ""),
                "strategy": strategy,
                "accepted": accepted,
                "reject_reason": reject_reason,
            },
            accepted=accepted,
            terminal_blocker=terminal_blocker or reject_reason,
        )
        return self._pipeline.append(event)

    def _append_diagnostic(self, event_type: str, payload: dict[str, Any]) -> None:
        path = Path("data/strategy_diagnostics") / f"{date.today().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(payload)
        row["event_type"] = event_type
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
