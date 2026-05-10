"""Tests for KoreaEquityEngine market rules."""

from __future__ import annotations

import json
import pandas as pd
import pytest

from backtest.engines.korea_equity import KoreaEquityEngine
from backtest.krx_symbol_cache import KRXSymbolMaster, save_symbol_master
from backtest.models import Position


def _make_bar(close: float = 70_000.0, open_: float | None = None) -> pd.Series:
    return pd.Series({"close": close, "open": close if open_ is None else open_})


def _engine(**overrides) -> KoreaEquityEngine:
    config = {"initial_cash": 500_000, "krx_symbol_lookup": False}
    config.update(overrides)
    return KoreaEquityEngine(config)


class TestTickLadders:
    def test_kospi_tick_over_100k_is_500(self) -> None:
        engine = _engine()
        engine._active_symbol = "005930.KS"
        assert engine.apply_slippage(120_001.0, 1) == 120_500.0

    def test_kosdaq_tick_over_50k_is_100(self) -> None:
        engine = _engine()
        engine._active_symbol = "091990.KQ"
        assert engine.apply_slippage(50_001.0, 1) == 50_100.0

    def test_etf_fixed_five_won_tick(self) -> None:
        engine = _engine(krx_instrument_types={"069500.KS": "etf"})
        engine._active_symbol = "069500.KS"
        assert engine.apply_slippage(50_001.0, 1) == 50_030.0

    def test_etn_fixed_five_won_tick(self) -> None:
        engine = _engine(krx_instrument_types={"500001.KS": "etn"})
        engine._active_symbol = "500001.KS"
        assert engine.apply_slippage(10_003.0, 1) == 10_010.0


class TestInstrumentTypes:
    def test_explicit_stock_type(self) -> None:
        engine = _engine(krx_instrument_types={"005930.KS": "stock"})
        assert engine.instrument_type("005930.KS") == "stock"

    def test_explicit_etf_type(self) -> None:
        engine = _engine(krx_instrument_types={"069500.KS": "etf"})
        assert engine.instrument_type("069500.KS") == "etf"

    def test_explicit_etn_type(self) -> None:
        engine = _engine(krx_instrument_types={"500001.KS": "etn"})
        assert engine.instrument_type("500001.KS") == "etn"

    def test_cache_resolves_etf_without_lookup(self, tmp_path) -> None:
        cache_path = tmp_path / "krx_symbol_master.json"
        save_symbol_master(
            KRXSymbolMaster(
                reference_date="20260425",
                etf_tickers={"069500"},
                etn_tickers=set(),
            ),
            cache_path,
        )
        engine = _engine(krx_symbol_cache_path=str(cache_path))
        assert engine.instrument_type("069500.KS") == "etf"

    def test_cache_resolves_etn_without_lookup(self, tmp_path) -> None:
        cache_path = tmp_path / "krx_symbol_master.json"
        save_symbol_master(
            KRXSymbolMaster(
                reference_date="20260425",
                etf_tickers=set(),
                etn_tickers={"500001"},
            ),
            cache_path,
        )
        engine = _engine(krx_symbol_cache_path=str(cache_path))
        assert engine.instrument_type("500001.KS") == "etn"


class TestSettlementAndLongSell:
    def test_engine_exposes_t_plus_2(self) -> None:
        assert _engine().settlement_cycle_days == 2

    def test_same_day_long_sell_allowed(self) -> None:
        engine = _engine()
        ts = pd.Timestamp("2026-04-27 09:00:00")
        engine.positions["005930.KS"] = Position(
            symbol="005930.KS",
            direction=1,
            entry_price=70_000.0,
            entry_time=ts,
            size=10,
            leverage=1.0,
            entry_bar_idx=0,
            entry_commission=0.0,
        )
        assert engine.can_execute("005930.KS", 0, _make_bar()) is True


class TestShortSelling:
    def test_short_disabled_by_default(self) -> None:
        assert _engine().can_execute("005930.KS", -1, _make_bar()) is False

    def test_covered_short_requires_opt_in(self) -> None:
        engine = _engine(allow_covered_short=True, covered_short_symbols=["005930"])
        assert engine.can_execute("005930.KS", -1, _make_bar()) is True

    def test_covered_short_respects_symbol_whitelist(self) -> None:
        engine = _engine(allow_covered_short=True, covered_short_symbols=["000660"])
        assert engine.can_execute("005930.KS", -1, _make_bar()) is False

    def test_short_etf_still_blocked_without_etp_opt_in(self) -> None:
        engine = _engine(
            allow_covered_short=True,
            covered_short_symbols=["069500"],
            krx_instrument_types={"069500.KS": "etf"},
        )
        assert engine.can_execute("069500.KS", -1, _make_bar(50_000.0)) is False

    def test_short_etf_allowed_with_etp_opt_in(self) -> None:
        engine = _engine(
            allow_covered_short=True,
            allow_short_etp=True,
            covered_short_symbols=["069500"],
            krx_instrument_types={"069500.KS": "etf"},
        )
        assert engine.can_execute("069500.KS", -1, _make_bar(50_000.0)) is True


class TestCosts:
    def test_kospi_stock_sell_tax_applies_on_close(self) -> None:
        engine = _engine(commission_rate=0.0)
        engine._active_symbol = "005930.KS"
        comm = engine.calc_commission(10.0, 70_000.0, 1, is_open=False)
        assert comm == pytest.approx(10.0 * 70_000.0 * 0.0005)

    def test_kosdaq_stock_sell_tax_applies_on_close(self) -> None:
        engine = _engine(commission_rate=0.0)
        engine._active_symbol = "091990.KQ"
        comm = engine.calc_commission(10.0, 70_000.0, 1, is_open=False)
        assert comm == pytest.approx(10.0 * 70_000.0 * 0.0020)

    def test_etf_sell_tax_is_zero_by_default(self) -> None:
        engine = _engine(commission_rate=0.0, krx_instrument_types={"069500.KS": "etf"})
        engine._active_symbol = "069500.KS"
        comm = engine.calc_commission(10.0, 50_000.0, 1, is_open=False)
        assert comm == 0.0

    def test_etn_sell_tax_is_zero_by_default(self) -> None:
        engine = _engine(commission_rate=0.0, krx_instrument_types={"500001.KS": "etn"})
        engine._active_symbol = "500001.KS"
        comm = engine.calc_commission(10.0, 10_000.0, 1, is_open=False)
        assert comm == 0.0
