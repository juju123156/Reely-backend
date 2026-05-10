---
name: strategy-improve-from-history
description: Turn trade history, paper/live execution logs, and past strategy artifacts into concrete improvement hypotheses, comparison artifacts, and approval-gated promotion decisions.
category: tool
---

# Strategy Improve From History

## Purpose

Use this skill when the user wants:

- to improve an existing strategy using real trading history
- to compare paper/live behavior with the original backtest
- to generate small, testable strategy changes instead of inventing a brand-new strategy

This is a research and promotion workflow, not a direct trading signal.

## Workflow

1. **Analyze history**
   - `analyze_strategy_history(history_path=...)`
   - writes `artifacts/diagnostic_report.json`
2. **Generate improvement candidates**
   - `generate_improvement_candidates(diagnostic_path="artifacts/diagnostic_report.json")`
   - writes `artifacts/improvement_candidates.json`
3. **Evaluate candidates**
   - run candidate backtests externally or with the orchestrator
   - assemble a comparison payload
   - `evaluate_improvement_candidates(comparison_path=...)`
   - writes:
     - `artifacts/improvement_comparison.json`
     - `artifacts/promotion_decision.json`

## Inputs

Recommended history fields:

- `symbol`
- `entry_time`
- `exit_time`
- `side`
- `entry_price`
- `exit_price`
- `pnl`
- `hold_minutes` or `hold_days`
- `entry_reason`
- `exit_reason`
- `strategy_id`
- `strategy_version`

Optional but high-value:

- `selected_symbols`
- `symbol_scores`
- `entry_signal_snapshot`
- `entry_signal_snapshot.ranked_candidates`
- `entry_signal_snapshot.top_ranked_not_selected`
- `exit_policy_snapshot`
- `market_regime`
- `session_bucket`

If available, enrich `ranked_candidates` with forward outcome fields such as:

- `realized_pnl`
- `forward_return`
- `future_return`

That allows the improver to detect when rejected symbols repeatedly outperform the selected ones.

## Design Rules

- generate **small modifications**, not total rewrites
- prefer parameter shifts and filters over entirely new logic
- default recommendation is to keep the baseline unless comparison evidence is clearly better
- promotion should require:
  - enough trades
  - no material drawdown deterioration
  - no recent-window collapse
  - stable behavior after costs

## Candidate Types

Good:

- tighten `time_stop`
- remove weak symbols or weak session buckets
- reduce `top_n`
- add a stronger volume filter
- disable KOSDAQ if it is consistently harmful
- reduce size in high-volatility names
- tighten selection score threshold when rejected symbols often beat selected ones
- re-weight ranking inputs when top-ranked rejects consistently outperform

Bad:

- "invent a new AI strategy"
- "change everything at once"
- "promote because total return is higher but trade count collapsed"

## Deliverables

Always present:

1. the main weaknesses found in the history
2. the smallest candidate changes worth testing
3. what the comparison says versus baseline
4. whether promotion is approved, rejected, or still paper-only
