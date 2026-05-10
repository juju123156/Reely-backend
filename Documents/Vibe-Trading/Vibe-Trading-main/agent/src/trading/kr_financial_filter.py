"""KR stock financial loss filter.

Filters out Korean stocks (KOSPI/KOSDAQ) that show structural losses
by checking EPS across the last N quarter-end snapshots via pykrx.

Filter rule (default – "Plan B"):
  Exclude a symbol if EPS < 0 in 3 or more of the last 4 quarter-end dates.

EPS data is sourced from pykrx's get_market_fundamental_by_ticker(), which
reflects the most recently disclosed financial report as of each date.
Symbols with no available data are NOT excluded (safe default).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Sequence

logger = logging.getLogger(__name__)

_QUARTER_MONTH_DAYS = {3: 26, 6: 25, 9: 25, 12: 26}


def _last_quarter_end_dates(n: int = 4) -> list[str]:
    """Return last n quarter-end check dates as YYYYMMDD strings.

    Uses the 25th–26th of each quarter-end month so the date is safely before
    the actual quarter close, avoiding weekends and ensuring KRX data exists.
    """
    today = date.today()
    results: list[str] = []
    year = today.year

    while len(results) < n:
        for month in (12, 9, 6, 3):
            day = _QUARTER_MONTH_DAYS[month]
            check = date(year, month, day)
            if check < today:
                results.append(check.strftime("%Y%m%d"))
                if len(results) >= n:
                    return results
        year -= 1

    return results


def _fetch_eps_snapshot(date_str: str, symbols: frozenset[str]) -> dict[str, float]:
    """Return EPS for requested symbols on the given date via pykrx."""
    from pykrx import stock as krx_stock  # type: ignore[import]

    df = krx_stock.get_market_fundamental_by_ticker(date_str, market="ALL")
    if df is None or df.empty:
        return {}

    result: dict[str, float] = {}
    for sym in symbols:
        if sym in df.index:
            try:
                result[sym] = float(df.loc[sym, "EPS"])
            except (KeyError, TypeError, ValueError):
                pass
    return result


def filter_loss_making_kr_symbols(
    symbols: Sequence[str],
    *,
    n_quarters: int = 4,
    min_loss_quarters: int = 3,
) -> list[str]:
    """Return KR stock codes that should be excluded due to structural losses.

    A symbol is marked as structurally loss-making when its disclosed EPS
    was negative in `min_loss_quarters` or more of the last `n_quarters`
    quarter-end snapshots.

    Args:
        symbols: Candidate KR stock codes (6-digit, e.g. "005930").
        n_quarters: How many quarter-end snapshots to check (default 4).
        min_loss_quarters: Threshold for exclusion (default 3).

    Returns:
        List of symbol codes to exclude. Empty list if pykrx is unavailable.
    """
    if not symbols:
        return []

    try:
        import pykrx  # noqa: F401 – availability check only
    except ImportError:
        logger.warning(
            "pykrx not installed – KR financial filter disabled. "
            "Run: pip install pykrx"
        )
        return []

    symbols_list = list(dict.fromkeys(symbols))  # deduplicate, preserve order
    symbols_frozen = frozenset(symbols_list)
    dates = _last_quarter_end_dates(n_quarters)

    # eps_history[symbol] = list of EPS values (None = data unavailable)
    eps_history: dict[str, list[float | None]] = {sym: [] for sym in symbols_list}

    for date_str in dates:
        try:
            snapshot = _fetch_eps_snapshot(date_str, symbols_frozen)
        except Exception as exc:
            logger.debug("pykrx EPS fetch failed for %s: %s", date_str, exc)
            for sym in symbols_list:
                eps_history[sym].append(None)
            continue

        for sym in symbols_list:
            eps_history[sym].append(snapshot.get(sym))

    to_exclude: list[str] = []
    for sym in symbols_list:
        values = eps_history[sym]
        valid = [v for v in values if v is not None]

        if not valid:
            logger.debug("No EPS data for %s – keeping in universe", sym)
            continue

        negative_count = sum(1 for v in valid if v < 0)
        if negative_count >= min_loss_quarters:
            logger.info(
                "Excluding %s: EPS negative in %d/%d quarter snapshots",
                sym,
                negative_count,
                len(valid),
            )
            to_exclude.append(sym)

    return to_exclude
