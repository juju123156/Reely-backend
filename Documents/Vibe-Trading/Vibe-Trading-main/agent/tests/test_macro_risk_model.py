from __future__ import annotations

from src.trading.scalping.macro_overnight_feed import MacroOvernightFeedEngine, ManualMacroAdapter
from src.trading.scalping.macro_risk_model import MacroRiskModel


def test_macro_feed_quality_full_partial_missing():
    full = MacroOvernightFeedEngine([ManualMacroAdapter({
        "nasdaq_futures_pct": 0.004,
        "usdkrw_pct": -0.002,
        "korea_night_futures_pct": 0.003,
        "sox_pct": 0.006,
        "nvda_pct": 0.01,
    })]).snapshot()
    partial = MacroOvernightFeedEngine([ManualMacroAdapter({"nasdaq_futures_pct": -0.01})]).snapshot()
    missing = MacroOvernightFeedEngine().snapshot()

    assert full.data_quality == "full"
    assert partial.data_quality == "partial"
    assert missing.data_quality == "missing"


def test_macro_risk_semiconductor_weights_sox_and_nvda_more():
    snapshot = MacroOvernightFeedEngine([ManualMacroAdapter({
        "nasdaq_futures_pct": -0.01,
        "usdkrw_pct": 0.002,
        "korea_night_futures_pct": -0.005,
        "sox_pct": -0.03,
        "nvda_pct": -0.04,
    })]).snapshot()

    risk = MacroRiskModel().score(snapshot, sector="semiconductor")

    assert risk.data_quality == "full"
    assert risk.macro_risk_score > 30
    assert risk.components["sox_pct"] > 0
    assert risk.components["nvda_pct"] > 0

