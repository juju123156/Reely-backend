"""Report-only threshold A/B manifest.

The manifest records candidate parameter comparisons for post-close analysis.
It never applies changes to live configuration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ThresholdABVariant:
    name: str
    strategy: str
    parameters: dict[str, Any]
    hypothesis: str = ""
    min_shadow_samples: int = 100


@dataclass(frozen=True)
class ThresholdABManifest:
    variants: list[ThresholdABVariant]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    report_only: bool = True
    auto_apply: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": "threshold_ab_manifest",
            "created_at": self.created_at,
            "report_only": self.report_only,
            "auto_apply": self.auto_apply,
            "variants": [asdict(v) for v in self.variants],
        }


def write_threshold_ab_manifest(
    manifest: ThresholdABManifest,
    *,
    output_dir: str | Path = "data/strategy_reports",
    report_date: date | None = None,
) -> Path:
    if not manifest.report_only or manifest.auto_apply:
        raise ValueError("threshold A/B manifest must remain report-only and auto_apply=false")
    day = (report_date or date.today()).isoformat()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"threshold_ab_manifest_{day}.json"
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path
