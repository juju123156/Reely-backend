from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.trading.scalping.funnel_sentinel import build_buy_funnel_sentinel_report
from src.trading.scalping.gatekeeper_replay import GatekeeperReplayStore, GatekeeperSnapshot
from src.trading.scalping.holding_exit_sentinel import build_holding_exit_sentinel_report
from src.trading.scalping.missed_entry_counterfactual import (
    AVOIDED_LOSER,
    MISSED_WINNER,
    classify_window,
)
from src.trading.scalping.pipeline_events import PipelineEventLogger, event_from_diagnostic, make_record_id
from src.trading.scalping.regime_runtime import (
    ExecutionQualityGate,
    ExecutionQualityInputs,
    LatencyState,
    QuoteHealthMonitor,
)
from src.trading.scalping.threshold_ab_manifest import (
    ThresholdABManifest,
    ThresholdABVariant,
    write_threshold_ab_manifest,
)


def test_pipeline_event_logger_writes_record_id(tmp_path: Path) -> None:
    logger = PipelineEventLogger(tmp_path)
    record_id = make_record_id("005930", "leader_only_shallow_pullback", seed="unit")
    event = event_from_diagnostic(
        record_id=record_id,
        stage="strategy_evaluated",
        payload={
            "symbol": "005930",
            "strategy": "leader_only_shallow_pullback",
            "reject_reason": "leader_score_below",
            "metrics": {"expected_entry_price": 70000},
        },
    )

    row = logger.append(event)

    assert row["record_id"] == record_id
    assert row["terminal_blocker"] == "leader_score_below"
    path = tmp_path / f"{date.today().isoformat()}.jsonl"
    saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert saved["stage"] == "strategy_evaluated"


def test_gatekeeper_replay_detects_mismatch(tmp_path: Path) -> None:
    store = GatekeeperReplayStore(tmp_path)
    store.append(
        GatekeeperSnapshot(
            record_id="r1",
            symbol="005930",
            strategy="leader_only_shallow_pullback",
            final_decision="block",
            terminal_blocker="stale_quote",
        )
    )

    mismatches = store.replay(lambda row: "allow")

    assert len(mismatches) == 1
    assert mismatches[0]["expected_decision"] == "block"
    assert mismatches[0]["actual_decision"] == "allow"


def test_quote_health_and_execution_quality_block_stale_quote() -> None:
    monitor = QuoteHealthMonitor()
    quote = monitor.classify(quote_age_ms=3500, tick_age_ms=100, orderbook_age_sec=0.5)
    quality = ExecutionQualityGate().score(
        ExecutionQualityInputs(
            quote_age_ms=quote.quote_age_ms,
            websocket_gap_ms=quote.tick_age_ms,
            depth_levels_available=3,
        )
    )

    assert quote.latency_state == LatencyState.DANGER
    assert quote.blocked_reason == "stale_quote"
    assert quality.blocked is True
    assert quality.blocked_reason == "stale_quote"


def test_counterfactual_classification() -> None:
    assert classify_window({"mfe_pct": 0.012, "mae_pct": -0.004, "net_expectancy": 0.004}) == MISSED_WINNER
    assert classify_window({"mfe_pct": 0.002, "mae_pct": -0.010, "net_expectancy": -0.006}) == AVOIDED_LOSER


def test_buy_funnel_sentinel_is_report_only(tmp_path: Path) -> None:
    diag = tmp_path / "diag"
    pipe = tmp_path / "pipe"
    out = tmp_path / "out"
    diag.mkdir()
    day = date.today().isoformat()
    (diag / f"{day}.jsonl").write_text(
        json.dumps({
            "event_type": "route_summary",
            "timestamp": "2099-01-01T09:30:00",
            "raw_scan_count": 10,
            "strategy_candidate_count_by_strategy": {},
        })
        + "\n",
        encoding="utf-8",
    )

    report = build_buy_funnel_sentinel_report(
        diagnostics_dir=diag,
        pipeline_dir=pipe,
        output_dir=out,
    )

    assert report["report_only"] is True
    assert report["recommended_check"] == "inspect_strategy_candidate_to_signal"


def test_holding_exit_sentinel_is_report_only(tmp_path: Path) -> None:
    diag = tmp_path / "diag"
    out = tmp_path / "out"
    diag.mkdir()
    day = date.today().isoformat()
    (diag / f"{day}.jsonl").write_text(
        "\n".join([
            json.dumps({"event_type": "live_order_fill", "side": "buy", "symbol": "005930"}),
            json.dumps({
                "event_type": "orderbook_stability_snapshot",
                "symbol": "005930",
                "microprice_edge": -0.001,
                "orderbook_flicker_rate": 0.6,
            }),
        ])
        + "\n",
        encoding="utf-8",
    )

    report = build_holding_exit_sentinel_report(diagnostics_dir=diag, output_dir=out)

    assert report["report_only"] is True
    assert report["open_entry_count_estimate"] == 1
    assert "microprice_worsening" in report["suggested_exit_reasons"]


def test_threshold_ab_manifest_forbids_auto_apply(tmp_path: Path) -> None:
    manifest = ThresholdABManifest(
        variants=[
            ThresholdABVariant(
                name="leader_score_60",
                strategy="leader_only_shallow_pullback",
                parameters={"leader_score_min": 60},
            )
        ]
    )
    path = write_threshold_ab_manifest(manifest, output_dir=tmp_path)
    assert path.exists()

    bad = ThresholdABManifest(variants=[], report_only=False, auto_apply=True)
    try:
        write_threshold_ab_manifest(bad, output_dir=tmp_path)
    except ValueError as exc:
        assert "report-only" in str(exc)
    else:
        raise AssertionError("auto-apply threshold manifest must be rejected")
