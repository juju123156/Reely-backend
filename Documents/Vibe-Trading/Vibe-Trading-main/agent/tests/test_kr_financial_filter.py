"""Tests for kr_financial_filter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.trading.kr_financial_filter import (
    _last_quarter_end_dates,
    filter_loss_making_kr_symbols,
)


def test_last_quarter_end_dates_returns_n_dates():
    dates = _last_quarter_end_dates(4)
    assert len(dates) == 4
    # All should be valid YYYYMMDD strings
    for d in dates:
        assert len(d) == 8
        assert d.isdigit()
    # Should be in descending order (most recent first)
    assert dates == sorted(dates, reverse=True)


def test_filter_empty_symbols():
    result = filter_loss_making_kr_symbols([])
    assert result == []


def _make_fundamental_df(eps_map: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"BPS": 0, "PER": 0, "PBR": 0, "EPS": eps_map, "DIV": 0, "DPS": 0},
        index=list(eps_map.keys()),
    )


def _with_pykrx_mocked(fn):
    """Decorator: mock pykrx availability so tests run without the package installed."""
    import sys
    from unittest.mock import patch

    pykrx_stub = MagicMock()

    def wrapper(*args, **kwargs):
        with patch.dict(sys.modules, {"pykrx": pykrx_stub, "pykrx.stock": pykrx_stub}):
            return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


@_with_pykrx_mocked
@patch("src.trading.kr_financial_filter._fetch_eps_snapshot")
def test_excludes_symbol_with_3_negative_quarters(mock_fetch):
    # 3 negative, 1 positive → should be excluded
    mock_fetch.side_effect = [
        {"005930": -100.0, "000660": 500.0},
        {"005930": -200.0, "000660": 600.0},
        {"005930": -50.0,  "000660": 400.0},
        {"005930": 10.0,   "000660": 300.0},
    ]
    excluded = filter_loss_making_kr_symbols(
        ["005930", "000660"],
        n_quarters=4,
        min_loss_quarters=3,
    )
    assert "005930" in excluded
    assert "000660" not in excluded


@_with_pykrx_mocked
@patch("src.trading.kr_financial_filter._fetch_eps_snapshot")
def test_keeps_symbol_with_2_negative_quarters(mock_fetch):
    # 2 negative, 2 positive → should NOT be excluded (threshold is 3)
    mock_fetch.side_effect = [
        {"005930": -100.0},
        {"005930": -200.0},
        {"005930": 300.0},
        {"005930": 400.0},
    ]
    excluded = filter_loss_making_kr_symbols(["005930"], n_quarters=4, min_loss_quarters=3)
    assert "005930" not in excluded


@_with_pykrx_mocked
@patch("src.trading.kr_financial_filter._fetch_eps_snapshot")
def test_keeps_symbol_with_no_data(mock_fetch):
    # All None → safe default: do not exclude
    mock_fetch.side_effect = [{}, {}, {}, {}]
    excluded = filter_loss_making_kr_symbols(["999999"], n_quarters=4, min_loss_quarters=3)
    assert "999999" not in excluded


@_with_pykrx_mocked
@patch("src.trading.kr_financial_filter._fetch_eps_snapshot")
def test_fetch_failure_treated_as_missing(mock_fetch):
    # Simulate pykrx errors on 3 dates, success with positive EPS on 1
    mock_fetch.side_effect = [
        Exception("network error"),
        Exception("network error"),
        Exception("network error"),
        {"005930": 100.0},
    ]
    excluded = filter_loss_making_kr_symbols(["005930"], n_quarters=4, min_loss_quarters=3)
    # Only 1 valid value (positive) → not excluded
    assert "005930" not in excluded


def test_no_pykrx_returns_empty(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pykrx":
            raise ImportError("pykrx not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    result = filter_loss_making_kr_symbols(["005930", "000660"])
    assert result == []
