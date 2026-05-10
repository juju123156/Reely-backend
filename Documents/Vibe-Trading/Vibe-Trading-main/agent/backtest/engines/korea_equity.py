"""Korea equity backtest engine.

Market rules encoded here focus on the cash equity market:
  - KOSPI / KOSDAQ tick ladders are different
  - ETFs / ETNs use a fixed KRW 5 tick
  - Trading unit is 1 share
  - Settlement is T+2, but same-day sell of a long position is allowed
  - Short selling is disabled by default; covered short is opt-in

This engine intentionally keeps broker-specific commission defaults minimal and
pushes them into config, while encoding market-level constraints directly.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.krx_symbol_cache import KRXSymbolMaster, load_symbol_master, save_symbol_master


def _base_code(symbol: str) -> str:
    upper = symbol.strip().upper()
    if "." in upper:
        return upper.split(".", 1)[0]
    return upper


def _board(symbol: str) -> str:
    upper = symbol.strip().upper()
    if upper.endswith(".KQ"):
        return "kosdaq"
    return "kospi"


class KoreaInstrumentResolver:
    """Resolve KRX product type with config override + best-effort pykrx lookup."""

    def __init__(self, config: dict) -> None:
        explicit = config.get("krx_instrument_types") or {}
        self._explicit: Dict[str, str] = {
            _base_code(str(symbol)): str(kind).strip().lower()
            for symbol, kind in explicit.items()
        }
        self._lookup_enabled = bool(config.get("krx_symbol_lookup", True))
        self._reference_date = str(
            config.get("krx_reference_date")
            or pd.Timestamp.now(tz="UTC").strftime("%Y%m%d")
        )
        self._cache_path = Path(
            config.get("krx_symbol_cache_path") or str(Path.home() / ".vibe-trading" / "cache" / "krx_symbol_master.json")
        )
        self._loaded = False
        self._etf_tickers: set[str] = set()
        self._etn_tickers: set[str] = set()

    def instrument_type(self, symbol: str) -> str:
        code = _base_code(symbol)
        explicit = self._explicit.get(code)
        if explicit in {"stock", "etf", "etn"}:
            return explicit

        self._load_lookup()
        if code in self._etf_tickers:
            return "etf"
        if code in self._etn_tickers:
            return "etn"

        return "stock"

    def _load_lookup(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        cached = load_symbol_master(self._cache_path)
        self._etf_tickers = set(cached.etf_tickers)
        self._etn_tickers = set(cached.etn_tickers)

        if not self._lookup_enabled:
            return

        try:
            from pykrx import stock as pykrx_stock

            etf_tickers = set(pykrx_stock.get_etf_ticker_list(self._reference_date))
            etn_tickers = set(pykrx_stock.get_etn_ticker_list(self._reference_date))
            if etf_tickers or etn_tickers:
                self._etf_tickers = etf_tickers
                self._etn_tickers = etn_tickers
                save_symbol_master(
                    KRXSymbolMaster(
                        reference_date=self._reference_date,
                        etf_tickers=etf_tickers,
                        etn_tickers=etn_tickers,
                    ),
                    self._cache_path,
                )
        except Exception:
            # Keep best-effort cached metadata when refresh fails.
            return


def _tick_size(price: float, board: str, instrument_type: str) -> int:
    if instrument_type in {"etf", "etn"}:
        return 5

    if board == "kosdaq":
        if price < 1_000:
            return 1
        if price < 5_000:
            return 5
        if price < 10_000:
            return 10
        if price < 50_000:
            return 50
        return 100

    if price < 1_000:
        return 1
    if price < 5_000:
        return 5
    if price < 10_000:
        return 10
    if price < 50_000:
        return 50
    if price < 100_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def _snap_to_tick(price: float, tick: int, direction: int) -> float:
    if price <= 0:
        return 0.0

    steps = price / tick
    if direction >= 0:
        return float(math.ceil(steps) * tick)
    return float(math.floor(steps) * tick)


class KoreaEquityEngine(BaseEngine):
    """KR cash-equity engine for KOSPI/KOSDAQ stocks, ETFs, and ETNs."""

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}
        super().__init__(config)
        self.settlement_cycle_days: int = 2
        self.same_day_long_sell_allowed: bool = True
        self.allow_covered_short: bool = bool(config.get("allow_covered_short", False))
        self.allow_short_etp: bool = bool(config.get("allow_short_etp", False))
        self.covered_short_symbols: set[str] = {
            _base_code(str(symbol))
            for symbol in (config.get("covered_short_symbols") or [])
        }

        self.commission_rate: float = float(config.get("commission_rate", 0.00015))
        self.commission_min: float = float(config.get("commission_min", 0.0))
        self.slippage_rate: float = float(config.get("slippage", 0.0005))

        # 2026-01-01 rate restoration:
        # KOSPI 0.05%, KOSDAQ 0.20%.
        self.kospi_transaction_tax: float = float(config.get("kospi_transaction_tax", 0.0005))
        self.kosdaq_transaction_tax: float = float(config.get("kosdaq_transaction_tax", 0.0020))
        self.etf_transaction_tax: float = float(config.get("etf_transaction_tax", 0.0))
        self.etn_transaction_tax: float = float(config.get("etn_transaction_tax", 0.0))

        self._resolver = KoreaInstrumentResolver(config)

    def instrument_type(self, symbol: str) -> str:
        return self._resolver.instrument_type(symbol)

    def board(self, symbol: str) -> str:
        return _board(symbol)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Allow long trading; covered short is explicit opt-in only."""
        del bar
        instrument_type = self.instrument_type(symbol)

        if direction == -1:
            if not self.allow_covered_short:
                return False
            if instrument_type in {"etf", "etn"} and not self.allow_short_etp:
                return False
            if self.covered_short_symbols and _base_code(symbol) not in self.covered_short_symbols:
                return False
            return True

        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """KRX cash equities trade in whole shares."""
        del price
        return max(int(raw_size), 0)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Broker commission + market-level transaction tax on sell-side only."""
        notional = size * price
        commission = max(notional * self.commission_rate, self.commission_min)

        sell_side = (direction == 1 and not is_open) or (direction == -1 and is_open)
        if not sell_side:
            return commission

        instrument_type = self.instrument_type(self._active_symbol)
        if instrument_type == "etf":
            tax_rate = self.etf_transaction_tax
        elif instrument_type == "etn":
            tax_rate = self.etn_transaction_tax
        else:
            tax_rate = (
                self.kosdaq_transaction_tax
                if self.board(self._active_symbol) == "kosdaq"
                else self.kospi_transaction_tax
            )
        return commission + notional * tax_rate

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage, then snap to the correct KRX tick ladder."""
        slipped = price * (1 + direction * self.slippage_rate)
        instrument_type = self.instrument_type(self._active_symbol)
        tick = _tick_size(slipped, self.board(self._active_symbol), instrument_type)
        return _snap_to_tick(slipped, tick, direction)
