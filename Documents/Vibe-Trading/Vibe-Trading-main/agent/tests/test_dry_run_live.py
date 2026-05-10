"""dry_run_live 모드 E2E 테스트.

검증 항목:
1. PromotionState.DRY_RUN_LIVE 파싱 (신형 JSON 포맷)
2. live_allowed() = True, is_dry_run_live() = True
3. is_promotion_candidate() 플래그
4. decide_promotions(): shadow→dry_run_live 경로, dry_run_live→small_live 경로
5. write_promotion_state() 신형 포맷 round-trip
6. force_simulate=True 인 submit()  — API 차단, 즉시 FillEvent 반환
7. pipeline record_id가 fill future에 보존되는지
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.trading.scalping.strategy_promotion import (
    PromotionState,
    StrategyPromotionGate,
    decide_promotions,
    write_promotion_state,
)
from src.trading.scalping.order_executor import OrderExecutor, OrderRequest, OrderStatus


# ─────────────────────────────────────────────────────────────────────────────
# PromotionGate — 신형 JSON 포맷 로딩
# ─────────────────────────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class TestPromotionGateNewFormat:
    def test_dry_run_live_parsed(self, tmp_path):
        f = tmp_path / "current.json"
        _write_json(f, {
            "leader_only_shallow_pullback": {
                "promotion_state": "dry_run_live",
                "promotion_candidate": True,
            }
        })
        gate = StrategyPromotionGate(state_path=f)
        assert gate.state_for("leader_only_shallow_pullback") == PromotionState.DRY_RUN_LIVE

    def test_live_allowed_includes_dry_run_live(self, tmp_path):
        f = tmp_path / "current.json"
        _write_json(f, {
            "leader_only_shallow_pullback": {
                "promotion_state": "dry_run_live",
                "promotion_candidate": True,
            }
        })
        gate = StrategyPromotionGate(state_path=f)
        assert gate.live_allowed("leader_only_shallow_pullback") is True

    def test_is_dry_run_live(self, tmp_path):
        f = tmp_path / "current.json"
        _write_json(f, {
            "leader_only_shallow_pullback": {
                "promotion_state": "dry_run_live",
                "promotion_candidate": True,
            }
        })
        gate = StrategyPromotionGate(state_path=f)
        assert gate.is_dry_run_live("leader_only_shallow_pullback") is True
        assert gate.is_dry_run_live("vwap_reclaim") is False

    def test_is_promotion_candidate(self, tmp_path):
        f = tmp_path / "current.json"
        _write_json(f, {
            "leader_only_shallow_pullback": {
                "promotion_state": "shadow_only",
                "promotion_candidate": True,
            },
            "vwap_reclaim": {
                "promotion_state": "shadow_only",
                "promotion_candidate": False,
            },
        })
        gate = StrategyPromotionGate(state_path=f)
        assert gate.is_promotion_candidate("leader_only_shallow_pullback") is True
        assert gate.is_promotion_candidate("vwap_reclaim") is False

    def test_alias_dry_run_live(self, tmp_path):
        """shallow_pullback → leader_only_shallow_pullback alias로 dry_run_live 반환."""
        f = tmp_path / "current.json"
        _write_json(f, {
            "leader_only_shallow_pullback": {
                "promotion_state": "dry_run_live",
                "promotion_candidate": True,
            }
        })
        gate = StrategyPromotionGate(state_path=f)
        assert gate.live_allowed("shallow_pullback") is True

    def test_old_format_still_works(self, tmp_path):
        """구형 {"states": {...}} 포맷도 읽힌다."""
        f = tmp_path / "current.json"
        _write_json(f, {
            "states": {
                "leader_only_shallow_pullback": "small_live",
                "vwap_reclaim": "shadow_only",
            }
        })
        gate = StrategyPromotionGate(state_path=f)
        assert gate.state_for("leader_only_shallow_pullback") == PromotionState.SMALL_LIVE
        assert gate.state_for("vwap_reclaim") == PromotionState.SHADOW_ONLY

    def test_missing_file_returns_shadow_only(self, tmp_path):
        gate = StrategyPromotionGate(state_path=tmp_path / "missing.json")
        assert gate.state_for("leader_only_shallow_pullback") == PromotionState.SHADOW_ONLY
        assert gate.live_allowed("leader_only_shallow_pullback") is False


# ─────────────────────────────────────────────────────────────────────────────
# decide_promotions() 승격 경로
# ─────────────────────────────────────────────────────────────────────────────

class TestDecidePromotions:
    def test_shadow_to_dry_run_live_when_partial_evidence(self):
        stats = {
            "leader_only_shallow_pullback": {
                "sample_count": 35,
                "win_rate": 0.43,
                "avg_mfe_pct": 0.008,
                "avg_mae_pct": -0.005,
                "net_expectancy": 0.002,
                "mfe_1pct_hit_rate": 0.30,
                "mae_minus_0_8pct_hit_rate": 0.20,
            }
        }
        decisions = decide_promotions(stats)
        assert len(decisions) == 1
        assert decisions[0].state == PromotionState.DRY_RUN_LIVE
        assert "dry_run_candidate" in decisions[0].reason

    def test_dry_run_live_to_small_live_when_full_evidence(self, tmp_path):
        f = tmp_path / "current.json"
        _write_json(f, {
            "leader_only_shallow_pullback": {
                "promotion_state": "dry_run_live",
                "promotion_candidate": True,
            }
        })
        gate = StrategyPromotionGate(state_path=f)
        stats = {
            "leader_only_shallow_pullback": {
                "sample_count": 60,
                "win_rate": 0.50,
                "avg_mfe_pct": 0.012,
                "avg_mae_pct": -0.004,
                "net_expectancy": 0.0015,
                "mfe_1pct_hit_rate": 0.45,
                "mae_minus_0_8pct_hit_rate": 0.20,
            }
        }
        decisions = decide_promotions(stats, current_gate=gate)
        assert decisions[0].state == PromotionState.SMALL_LIVE
        assert "dry_run_passed" in decisions[0].reason

    def test_insufficient_evidence_stays_shadow(self):
        stats = {
            "leader_only_shallow_pullback": {
                "sample_count": 10,
                "win_rate": 0.30,
                "avg_mfe_pct": 0.005,
                "avg_mae_pct": -0.008,
                "net_expectancy": -0.001,
                "mfe_1pct_hit_rate": 0.10,
                "mae_minus_0_8pct_hit_rate": 0.40,
            }
        }
        decisions = decide_promotions(stats)
        assert decisions[0].state == PromotionState.SHADOW_ONLY

    def test_vwap_reclaim_dry_run_path(self):
        stats = {
            "vwap_reclaim": {
                "sample_count": 35,
                "win_rate": 0.42,
                "avg_mfe_pct": 0.008,
                "avg_mae_pct": -0.005,
                "net_expectancy": 0.001,
                "mfe_0_8pct_hit_rate": 0.40,
                "mae_minus_0_8pct_hit_rate": 0.20,
            }
        }
        decisions = decide_promotions(stats)
        assert decisions[0].state == PromotionState.DRY_RUN_LIVE


# ─────────────────────────────────────────────────────────────────────────────
# write_promotion_state() 신형 포맷 round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestWritePromotionState:
    def test_rich_format_written(self, tmp_path):
        from src.trading.scalping.strategy_promotion import PromotionDecision
        decisions = [
            PromotionDecision(
                strategy="leader_only_shallow_pullback",
                state=PromotionState.DRY_RUN_LIVE,
                reason="leader_shallow_dry_run_candidate",
                sample_count=35,
                net_expectancy=0.002,
                win_rate=0.43,
                avg_mfe=0.008,
                avg_mae=-0.005,
            )
        ]
        path = write_promotion_state(decisions, base_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        # 구형 호환 필드
        assert data["states"]["leader_only_shallow_pullback"] == "dry_run_live"
        # 신형 rich 필드
        entry = data["leader_only_shallow_pullback"]
        assert entry["promotion_state"] == "dry_run_live"
        assert entry["promotion_candidate"] is True
        assert "net_expectancy" in entry

    def test_round_trip_gate_reads_written_state(self, tmp_path):
        from src.trading.scalping.strategy_promotion import PromotionDecision
        decisions = [
            PromotionDecision(
                strategy="leader_only_shallow_pullback",
                state=PromotionState.DRY_RUN_LIVE,
                reason="test",
                sample_count=35,
            )
        ]
        path = write_promotion_state(decisions, base_dir=tmp_path)
        gate = StrategyPromotionGate(state_path=path)
        assert gate.state_for("leader_only_shallow_pullback") == PromotionState.DRY_RUN_LIVE
        assert gate.live_allowed("leader_only_shallow_pullback") is True
        assert gate.is_dry_run_live("leader_only_shallow_pullback") is True


# ─────────────────────────────────────────────────────────────────────────────
# OrderExecutor.submit(force_simulate=True)
# ─────────────────────────────────────────────────────────────────────────────

def _make_req(**kwargs) -> OrderRequest:
    defaults = dict(
        symbol="000660",
        side="buy",
        qty=10,
        price=50_000.0,
        order_type="limit",
        reason="entry_1",
        ref_id="test_record_001",
    )
    defaults.update(kwargs)
    return OrderRequest(**defaults)


class TestOrderExecutorForceSimulate:
    def test_force_simulate_blocks_api_call(self):
        adapter = MagicMock()
        executor = OrderExecutor(adapter=adapter, env="real", dry_run=False)
        req = _make_req()

        async def run():
            return await executor.submit(req, force_simulate=True)

        order_no = asyncio.run(run())
        assert order_no is not None
        assert order_no.startswith("DRL")
        adapter.place_order_cash.assert_not_called()

    def test_force_simulate_immediate_fill(self):
        adapter = MagicMock()
        executor = OrderExecutor(adapter=adapter, env="real", dry_run=False)
        req = _make_req()

        async def run():
            order_no = await executor.submit(req, force_simulate=True)
            return order_no, executor._records.get(order_no)

        order_no, record = asyncio.run(run())
        assert record is not None
        assert record.status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}
        assert record.filled_qty > 0

    def test_force_simulate_preserves_record_id(self):
        adapter = MagicMock()
        executor = OrderExecutor(adapter=adapter, env="real", dry_run=False)
        req = _make_req(ref_id="pipeline_event_abc123")

        async def run():
            order_no = await executor.submit(req, force_simulate=True)
            return executor._records.get(order_no)

        record = asyncio.run(run())
        assert record is not None
        assert record.record_id == "pipeline_event_abc123"

    def test_force_simulate_fill_future_resolves(self):
        adapter = MagicMock()
        executor = OrderExecutor(adapter=adapter, env="real", dry_run=False)
        req = _make_req()

        async def run():
            order_no = await executor.submit(req, force_simulate=True)
            fill = await executor.wait_fill(order_no, timeout=1.0)
            return fill

        fill = asyncio.run(run())
        assert fill is not None
        assert fill.filled_qty > 0

    def test_normal_dry_run_unaffected(self):
        """dry_run=True 는 force_simulate 없이도 시뮬레이션."""
        adapter = MagicMock()
        adapter.place_order_cash.return_value = {"status": "ok", "order_no": "DRY00001"}
        executor = OrderExecutor(adapter=adapter, env="demo", dry_run=True)
        req = _make_req()

        async def run():
            return await executor.submit(req)

        order_no = asyncio.run(run())
        assert order_no is not None

    def test_force_simulate_false_uses_dry_run_path(self):
        """force_simulate=False & dry_run=True → dry_run 경로 (API 미호출, DRY prefix)."""
        adapter = MagicMock()
        adapter.place_order_cash.return_value = {"status": "ok", "order_no": "DRY00001"}
        executor = OrderExecutor(adapter=adapter, env="demo", dry_run=True)
        req = _make_req()

        async def run():
            return await executor.submit(req, force_simulate=False)

        order_no = asyncio.run(run())
        # dry_run 모드에서 order_no가 반환된다
        assert order_no is not None
        # DRY_RUN_LIVE 접두사 DRL이 아님
        assert not (order_no or "").startswith("DRL")
