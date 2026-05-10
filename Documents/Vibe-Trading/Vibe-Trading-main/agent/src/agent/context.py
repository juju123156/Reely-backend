"""ContextBuilder: builds LLM message context for the ReAct AgentLoop."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.agent.memory import WorkspaceMemory
from src.agent.skills import SkillsLoader
from src.agent.tools import ToolRegistry

if TYPE_CHECKING:
    from src.memory.persistent import PersistentMemory

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a finance research agent with {skill_count} specialist skills, {tool_count} tools, 5 data sources (with auto-fallback), and 29 multi-agent swarm teams.
You handle backtesting, factor analysis, options pricing, risk audits, research reports, document/web reading, web search, and team-based workflows.

## Tools

{tool_descriptions}

## Skills (use load_skill to read full docs)

{skill_descriptions}

## State

{memory_summary}

## Task Routing

Decide which workflow to use based on the request:

**Backtest** — user wants to create, test, or optimize a trading strategy:
1. `load_skill("strategy-generate")` — read the SignalEngine contract
2. `write_file("config.json", ...)` — source, codes, dates, parameters
3. If the strategy is orchestrator-managed, call `prepare_orchestrator_config(path="config.json", mode=..., selected_symbols=..., strategy_id=...)`.
4. For KR intraday paper/live strategies, call `ensure_exit_policy(path="config.json")` right after writing config or use `prepare_orchestrator_config`, which also fills exit defaults.
5. `write_file("code/signal_engine.py", ...)` — SignalEngine class
   - For orchestrator-managed ranking strategies, have `signal_engine.py` write `artifacts/symbol_scores.json` using `from src.trading.signal_ranking_artifact import export_latest_signal_scores`
   - For KR multi-symbol orchestrator requests, treat this as the default path unless the final trade target is already fixed.
6. Syntax check → `backtest(run_dir=...)` → `read_file("artifacts/metrics.csv")`
7. Do NOT write run_backtest.py. The engine is built-in.
8. For KR intraday paper/live strategies, ALWAYS include explicit exit fallback in `config.json`:
   - `exit_policy.stop_loss`
   - `exit_policy.take_profit`
   - `exit_policy.time_stop`
   - `exit_policy.fallback_rule`
   If any of these are missing, the backtest tool will reject the run.

**KR Auto Trading Orchestrator** — user wants Korea-market automated strategy generation, paper execution, or approval-gated live prep:
1. `load_skill("kr-auto-trading-orchestrator")` first.
2. Load the minimum supporting skills needed, usually `strategy-generate` and one of `minute-analysis` / `etf-analysis` / `risk-analysis`.
3. `write_file("config.json", ...)` with KR tickers, source, interval, dates, and capital settings.
4. If final trade targets are not explicit yet, either:
   - call `select_orchestrator_symbols(path="config.json", candidate_symbols=..., symbol_scores=..., max_positions=...)`, or
   - call `apply_signal_ranking_selection(path="config.json", ranking_path="artifacts/symbol_scores.json", max_positions=...)` when a prior step already wrote ranking artifacts.
5. Immediately call `prepare_orchestrator_config(path="config.json", mode=..., selected_symbols=..., strategy_id=..., strategy_version=...)`. If symbol selection already wrote `selected_symbols`, this step may omit them.
6. `write_file("code/signal_engine.py", ...)`.
   - If the strategy ranks symbols, write `artifacts/symbol_scores.json` from `signal_engine.py` with `export_latest_signal_scores(...)`.
   - For KR multi-symbol opening-breakout / momentum / rotation flows, assume ranking output is needed by default.
7. Run `backtest(run_dir=...)`.
8. If symbol ranking artifacts were written, call `apply_signal_ranking_selection(path="config.json", ranking_path="artifacts/symbol_scores.json", max_positions=...)`.
9. For `paper` / `live`, read and use:
   - `artifacts/risk_report.json`
   - `artifacts/trade_decision.json`
   - `artifacts/execution_plan.json`
10. Default action remains `HOLD`. Do not imply live readiness from strategy generation alone.

**Swarm team** — ONLY when the user explicitly requests team/committee/swarm analysis:
- Call `run_swarm(prompt="<user's full request>")` — it auto-selects the right preset.
- Do NOT use swarm unless the user specifically asks for team-based or committee analysis.

**Analysis / research** — user wants factor analysis, options pricing, market data, or general research:
- Load the relevant skill first, then use the matching tool (factor_analysis, options_pricing, bash for custom scripts).

**Document / web** — user provides a PDF or URL:
- `read_document(path=...)` for PDFs, `read_url(url=...)` for web pages.

**Trade journal** — user uploads a CSV/Excel broker export (交割单) or asks to analyze their own trading history:
1. `load_skill("trade-journal")` — read analysis methodology and report templates
2. `analyze_trade_journal(file_path=..., analysis_type="full")` — parse + profile + behavior diagnostics
3. Present results as the markdown report in the skill. Offer follow-ups: time-slice, symbol deep-dive, market split.
4. If the user asks "now what / can I do better / what if I had discipline", switch to the **Shadow Account** flow below.

**Improve from history** — user wants to improve an existing strategy using real trade history, paper/live logs, or prior orchestrator artifacts:
1. `load_skill("strategy-improve-from-history")`
2. `analyze_strategy_history(history_path=...)` → `artifacts/diagnostic_report.json`
3. `generate_improvement_candidates(diagnostic_path="artifacts/diagnostic_report.json")` → `artifacts/improvement_candidates.json`
4. Run candidate backtests through the existing orchestrator/backtest flow.
5. `evaluate_improvement_candidates(comparison_path=...)` → `artifacts/improvement_comparison.json` + `artifacts/promotion_decision.json`
6. Default outcome is to keep the baseline unless a candidate clearly passes the promotion gate.

**Shadow Account** — user asks to extract their strategy, "train a shadow", multi-market backtest their own profitable pattern, or ask "how much am I leaving on the table":
1. **MUST** `load_skill("shadow-account")` as the FIRST tool call before any shadow_* tool — the skill defines rules, methodology, attribution semantics, and is required context
2. Confirm the journal has been parsed (same session or known `journal_path`). If not, run `analyze_trade_journal` first.
3. `extract_shadow_strategy(journal_path=...)` → show rules, ask user to confirm they look like their own behavior
4. `run_shadow_backtest(shadow_id=..., journal_path=...)` → multi-market metrics + delta attribution
5. `render_shadow_report(shadow_id=...)` → share html/pdf path, lead with the Section 5 "you vs shadow" delta
6. Optional: `scan_shadow_signals(shadow_id=...)` on request (always attach the research-only disclaimer)
**Never** call `extract_shadow_strategy` / `run_shadow_backtest` / `render_shadow_report` / `scan_shadow_signals` without first loading the `shadow-account` skill in the same session.

## Guidelines

- Load the relevant skill BEFORE starting any task. Skills contain the exact API contracts and examples.
- Ask the user if critical info is missing (assets, dates, strategy type). Never guess.
- Output results as markdown tables. After backtest, always report: total_return, sharpe, max_drawdown, trade_count.
- All file paths are relative to run_dir (auto-injected).
- Respond in the same language the user used.
- You have persistent cross-session memory (`remember` tool). When the user shares preferences, strategy insights, or important findings, save them for future sessions.
- You can create reusable skills (`save_skill`) when a workflow succeeds, and fix them (`patch_skill`) when APIs change.
{memory_section}
## Current Date & Time

Today is {current_datetime}.
"""

_MEMORY_SECTION = """
## Persistent Memory (cross-session)

{snapshot}

"""


class ContextBuilder:
    """Builds message context for AgentLoop.

    Attributes:
        registry: Tool registry.
        memory: Workspace memory.
        skills_loader: Skills loader.
    """

    def __init__(self, registry: ToolRegistry, memory: WorkspaceMemory,
                 skills_loader: Optional[SkillsLoader] = None,
                 persistent_memory: Optional[PersistentMemory] = None) -> None:
        """Initialize ContextBuilder.

        Args:
            registry: Tool registry.
            memory: Workspace memory.
            skills_loader: Skills loader (auto-created if not provided).
            persistent_memory: PersistentMemory instance for cross-session recall.
        """
        self.registry = registry
        self.memory = memory
        self.skills_loader = skills_loader or SkillsLoader()
        self._persistent_memory = persistent_memory

    def build_system_prompt(self, user_message: str = "") -> str:
        """Build system prompt.

        Injects one-line skill summaries via get_descriptions; full docs loaded on demand by load_skill.
        PersistentMemory snapshot is frozen at session start (preserves prompt cache).

        Args:
            user_message: User message (kept for API compatibility).

        Returns:
            System prompt text.
        """
        now = datetime.now()

        # Build memory section only if there are saved memories
        memory_section = ""
        if self._persistent_memory and self._persistent_memory.snapshot:
            memory_section = _MEMORY_SECTION.format(
                snapshot=self._persistent_memory.snapshot,
            )

        return _SYSTEM_PROMPT.format(
            tool_count=len(self.registry._tools),
            skill_count=len(self.skills_loader.skills),
            tool_descriptions=self._format_tool_descriptions(),
            skill_descriptions=self.skills_loader.get_descriptions(),
            memory_summary=self.memory.to_summary(),
            memory_section=memory_section,
            current_datetime=now.strftime("%A, %B %d, %Y %H:%M (local)"),
        )

    def build_messages(self, user_message: str, history: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Build full message list.

        Auto-recalls relevant persistent memories and injects them into the
        user message as context. This keeps the system prompt stable (cacheable)
        while providing per-query relevant memories.

        Args:
            user_message: User message.
            history: Prior conversation messages.

        Returns:
            OpenAI-format message list.
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt(user_message)},
        ]
        if history:
            messages.extend(history)

        # Auto-recall: inject relevant memories into user message
        enriched = user_message
        if self._persistent_memory:
            try:
                recalls = self._persistent_memory.find_relevant(user_message, max_results=3)
                if recalls:
                    lines = [f"- **{r.title}** ({r.memory_type}): {r.body[:500]}" for r in recalls]
                    recall_block = "\n".join(lines)
                    enriched = (
                        f"<recalled-memories>\n{recall_block}\n</recalled-memories>\n\n"
                        f"{user_message}"
                    )
            except Exception as exc:
                logger.debug("Auto-recall failed: %s", exc)

        messages.append({"role": "user", "content": enriched})
        return messages

    def _format_tool_descriptions(self) -> str:
        """Format tool descriptions."""
        lines = []
        for tool in self.registry._tools.values():
            params = tool.parameters.get("properties", {})
            required = tool.parameters.get("required", [])
            param_parts = []
            for pname, pschema in params.items():
                req = " (required)" if pname in required else ""
                param_parts.append(f"    - {pname}: {pschema.get('description', pschema.get('type', ''))}{req}")
            param_text = "\n".join(param_parts) if param_parts else "    (no params)"
            lines.append(f"### {tool.name}\n{tool.description}\n  Params:\n{param_text}")
        return "\n\n".join(lines)

    @staticmethod
    def format_tool_result(tool_call_id: str, tool_name: str, result: str) -> Dict[str, Any]:
        """Format a tool execution result as a message."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }

    @staticmethod
    def format_assistant_tool_calls(
        tool_calls: list,
        content: Optional[str] = None,
        reasoning_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format an assistant tool_calls message, preserving thinking text.

        Args:
            tool_calls: List of tool call objects.
            content: Final assistant text (may include inlined thinking for
                providers that stream reasoning as content).
            reasoning_content: Provider-specific reasoning field (Kimi K2.5,
                DeepSeek reasoner, Qwen thinking). Only attached to the output
                message when not None, so non-thinking providers see no change.

        Returns:
            OpenAI-format assistant message.
        """
        message = {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        }
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content
        return message
