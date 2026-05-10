from __future__ import annotations

from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "src" / "skills" / "strategy-generate"
SKILL_MD = SKILL_DIR / "SKILL.md"
EXAMPLE_PY = SKILL_DIR / "example_signal_engine_kr_orchestrator.py"


def test_strategy_generate_skill_links_kr_orchestrator_example() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "example_signal_engine_kr_orchestrator.py" in text
    assert "KR multi-symbol opening-strength ranking" in text


def test_kr_orchestrator_example_contains_ranking_export() -> None:
    text = EXAMPLE_PY.read_text(encoding="utf-8")

    assert "class SignalEngine" in text
    assert "export_latest_signal_scores" in text
    assert "kr opening strength rank" in text
    assert "top_n" in text
