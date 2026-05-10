"""Local cache for KRX symbol master metadata.

The cache is intentionally small and stores only what the backtest engine
needs for market-rule resolution:
  - ETF ticker set
  - ETN ticker set

Cache location defaults to ``~/.vibe-trading/cache/krx_symbol_master.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def default_cache_path() -> Path:
    return Path.home() / ".vibe-trading" / "cache" / "krx_symbol_master.json"


@dataclass(frozen=True)
class KRXSymbolMaster:
    reference_date: str
    etf_tickers: set[str]
    etn_tickers: set[str]

    @classmethod
    def empty(cls, reference_date: str = "") -> "KRXSymbolMaster":
        return cls(reference_date=reference_date, etf_tickers=set(), etn_tickers=set())

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "reference_date": self.reference_date,
            "etf_tickers": sorted(self.etf_tickers),
            "etn_tickers": sorted(self.etn_tickers),
        }


def load_symbol_master(path: Path | None = None) -> KRXSymbolMaster:
    cache_path = path or default_cache_path()
    if not cache_path.exists():
        return KRXSymbolMaster.empty()

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return KRXSymbolMaster.empty()

    return KRXSymbolMaster(
        reference_date=str(payload.get("reference_date") or ""),
        etf_tickers={str(item) for item in (payload.get("etf_tickers") or [])},
        etn_tickers={str(item) for item in (payload.get("etn_tickers") or [])},
    )


def save_symbol_master(master: KRXSymbolMaster, path: Path | None = None) -> Path:
    cache_path = path or default_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(master.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cache_path
