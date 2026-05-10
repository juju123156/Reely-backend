from __future__ import annotations

import json
from datetime import time as dtime
from pathlib import Path

from src.trading.scalping.strategy_params import StrategyParameterStore
from src.trading.scalping.strategy_router import IntradayStrategyRouter
from tests.test_strategy_router import _context, _tick


def test_strategy_parameter_store_overrides_json(tmp_path: Path):
    path = tmp_path / "strategies.json"
    path.write_text(json.dumps({
        "shallow_pullback": {"entry_exec_min": 999.0},
    }), encoding="utf-8")

    store = StrategyParameterStore(path)

    assert store.get("shallow_pullback", "entry_exec_min") == 999.0
    assert store.get("shallow_pullback", "entry_score") == 72.0


def test_router_uses_configured_shallow_threshold(tmp_path: Path):
    path = tmp_path / "strategies.json"
    path.write_text(json.dumps({
        "shallow_pullback": {"entry_exec_min": 999.0},
    }), encoding="utf-8")
    router = IntradayStrategyRouter(StrategyParameterStore(path))

    signals = router.route_tick(_tick(price=9_950), None, _context(dtime(9, 30), pullback_pct=0.006))

    assert any(s.strategy_name == "shallow_pullback" and s.reason == "exec_strength_below" for s in signals)
    assert not any(s.strategy_name == "shallow_pullback" and s.live_allowed for s in signals)
