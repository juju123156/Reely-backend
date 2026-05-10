from pathlib import Path

from src.agent.context import _SYSTEM_PROMPT  # noqa: SLF001


SKILL_DIR = Path(__file__).resolve().parents[1] / "src" / "skills" / "kr-auto-trading-orchestrator"
SKILL_MD = SKILL_DIR / "SKILL.md"
OPENAI_YAML = SKILL_DIR / "agents" / "openai.yaml"


def test_system_prompt_includes_kr_orchestrator_flow() -> None:
    assert "KR Auto Trading Orchestrator" in _SYSTEM_PROMPT
    assert 'load_skill("kr-auto-trading-orchestrator")' in _SYSTEM_PROMPT
    assert 'prepare_orchestrator_config(path="config.json"' in _SYSTEM_PROMPT
    assert 'select_orchestrator_symbols(path="config.json"' in _SYSTEM_PROMPT
    assert 'apply_signal_ranking_selection(path="config.json"' in _SYSTEM_PROMPT
    assert "export_latest_signal_scores" in _SYSTEM_PROMPT
    assert "KR multi-symbol orchestrator requests" in _SYSTEM_PROMPT
    assert "artifacts/trade_decision.json" in _SYSTEM_PROMPT


def test_skill_doc_requires_prepare_orchestrator_config_step() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "Mandatory tool sequence" in text
    assert 'select_orchestrator_symbols(path="config.json"' in text
    assert 'apply_signal_ranking_selection(path="config.json"' in text
    assert 'prepare_orchestrator_config(path="config.json"' in text
    assert "selected_symbols" in text
    assert "exit_policy" in text


def test_strategy_generate_skill_defaults_export_for_kr_multi_symbol() -> None:
    strategy_skill = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "skills"
        / "strategy-generate"
        / "SKILL.md"
    )
    text = strategy_skill.read_text(encoding="utf-8")

    assert "Default rule for KR orchestrator requests" in text
    assert "treat `export_latest_signal_scores(...)` as the default" in text
    assert "KR intraday opening-strength / momentum / rotation / relative-strength prompts" in text


def test_openai_yaml_mentions_config_persistence() -> None:
    text = OPENAI_YAML.read_text(encoding="utf-8")

    assert "prepare_orchestrator_config" in text
    assert "mode, selected_symbols, and KR intraday exit_policy" in text
