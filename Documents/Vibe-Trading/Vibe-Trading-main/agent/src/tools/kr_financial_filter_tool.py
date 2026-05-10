"""Tool: filter KR stocks with structural losses before symbol selection."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool


class KRFinancialFilterTool(BaseTool):
    """Exclude KR stocks with structural losses from a candidate universe.

    Checks the last 4 quarter-end EPS snapshots via pykrx and returns symbols
    where EPS was negative 3 or more times (default "Plan B" threshold).

    Typical usage:
      1. Call kr_financial_filter with your candidate symbols.
      2. Pass the returned excluded_symbols to select_orchestrator_symbols
         as exclude_symbols.
    """

    name = "kr_financial_filter"
    description = (
        "Filter Korean stock symbols (KOSPI/KOSDAQ) that show structural losses. "
        "Returns excluded_symbols (negative EPS in 3+ of last 4 quarters) and "
        "passed_symbols. Feed excluded_symbols into select_orchestrator_symbols "
        "exclude_symbols parameter."
    )
    is_readonly = True
    repeatable = True

    parameters = {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Candidate KR stock codes to check (6-digit, e.g. ['005930', '000660'])",
            },
            "n_quarters": {
                "type": "integer",
                "description": "Number of quarter-end snapshots to evaluate (default: 4)",
            },
            "min_loss_quarters": {
                "type": "integer",
                "description": "Min quarters with negative EPS required to exclude a symbol (default: 3)",
            },
        },
        "required": ["symbols"],
    }

    @classmethod
    def check_available(cls) -> bool:
        try:
            import pykrx  # noqa: F401
            return True
        except ImportError:
            return False

    def execute(self, **kwargs: Any) -> str:
        from src.trading.kr_financial_filter import filter_loss_making_kr_symbols

        symbols: list[str] = [str(s) for s in (kwargs.get("symbols") or [])]
        if not symbols:
            return json.dumps(
                {"status": "error", "error": "symbols list is empty"},
                ensure_ascii=False,
            )

        n_quarters = int(kwargs.get("n_quarters") or 4)
        min_loss_quarters = int(kwargs.get("min_loss_quarters") or 3)

        excluded = filter_loss_making_kr_symbols(
            symbols,
            n_quarters=n_quarters,
            min_loss_quarters=min_loss_quarters,
        )
        excluded_set = set(excluded)
        passed = [s for s in symbols if s not in excluded_set]

        return json.dumps(
            {
                "status": "ok",
                "checked": len(symbols),
                "excluded_count": len(excluded),
                "passed_count": len(passed),
                "excluded_symbols": excluded,
                "passed_symbols": passed,
            },
            ensure_ascii=False,
        )
