---
name: kr-auto-trading-orchestrator
description: Orchestrate Korea-market strategy discovery, backtesting, risk gating, and approval-based paper/live execution. Use when turning a trading idea, journal pattern, or research input into a disciplined KR trading workflow with hold-by-default behavior.
category: tool
---

## Goal

Convert a KR trading idea into a controlled workflow:

1. define universe and market regime
2. generate strategy code and config
3. run KR-aware backtest
4. apply risk gates
5. output `BUY` / `SELL` / `REDUCE` / `HOLD`
6. only prepare execution when approval and broker conditions are satisfied

Default action is always `HOLD`.

## Use When

- The user wants semi-automated or automated KR trading decisions
- A prompt, journal insight, or commit summary should become a strategy candidate
- A strategy must be validated before paper/live execution
- The user wants the system to choose and chain existing finance skills

Do not use this skill to place live orders directly without explicit approval and broker connectivity.

## Inputs

Collect or infer:

- market: `kr`
- universe: ticker list with `.KS` / `.KQ`
- intent: opening breakout / ETF rotation / pullback / mean reversion / other
- date range for backtest
- mode: `research`, `paper`, or `live`
- risk budget: max positions, max loss, stop rules
- instrument typing overrides for ETF / ETN when needed

If the universe is missing, ask for it or propose a narrow starter list.

## Orchestration Steps

### 1. Normalize the request

- convert KR symbols to `.KS` / `.KQ`
- separate stocks vs ETF / ETN if the user already specified them
- reject ambiguous requests like "just trade good Korean stocks"

### 2. Select supporting skills

Common routing:

- strategy generation: `strategy-generate`
- intraday logic: `minute-analysis`
- KR ETF selection: `etf-analysis`
- risk review: `risk-analysis`
- performance debug: `backtest-diagnose`
- journal-derived rules: `trade-journal`, `shadow-account`
- report output: `report-generate`

Load only the minimum set needed.

### 3. Build the candidate strategy

Write:

- `config.json`
- `code/signal_engine.py`

KR defaults:

- `source: "auto"`
- KR tickers only
- explicit `krx_instrument_types` for ETF / ETN if known
- long-only unless the user explicitly asks for covered short simulation

Mandatory tool sequence:

1. `write_file("config.json", ...)`
2. If the final symbols are not fixed yet, either:
   - `select_orchestrator_symbols(path="config.json", candidate_symbols=..., symbol_scores=..., max_positions=...)`
   - `apply_signal_ranking_selection(path="config.json", ranking_path="artifacts/symbol_scores.json", max_positions=...)`
3. `prepare_orchestrator_config(path="config.json", mode=..., selected_symbols=..., strategy_id=..., strategy_version=...)`
4. `write_file("code/signal_engine.py", ...)`
   - when the strategy ranks symbols, import `export_latest_signal_scores` from `src.trading.signal_ranking_artifact` and write `artifacts/symbol_scores.json`
5. `backtest(run_dir=...)`

Do not skip step 3 for orchestrator-managed strategies. That step is what persists:

- `mode`
- `selected_symbols`
- `exit_policy` for KR intraday `paper` / `live`
- `strategy_id`
- `strategy_version`

Use step 2 whenever the strategy first produces a universe and then has to narrow it to actual trade targets. The selection tool should be deterministic:

- rank candidates with explicit scores when available
- otherwise preserve the candidate order
- cap by `max_positions`
- store the audit trail in `symbol_selection`

If `signal_engine.py` or a research pre-step writes a ranking artifact, prefer `apply_signal_ranking_selection(...)` over manually repeating the scores in the tool call. Supported bridge formats:

- JSON: `{"symbol_scores": {...}}`
- JSON: `{"scores": {...}, "ranked_symbols": [...]}`
- JSON snapshots: `{"snapshots": [{"timestamp": "...", "symbol_scores": {...}}]}`
- CSV: `symbol,score[,timestamp,rank]`

The preferred source is now the generated strategy itself:

```python
from src.trading.signal_ranking_artifact import export_latest_signal_scores

signal_map = engine.generate(data_map)
export_latest_signal_scores(signal_map, metadata={"selection_reason": "latest signal rank"})
```

### 4. Run backtest

Use the built-in backtest flow and read:

- trade count
- total return
- max drawdown
- win rate
- profit factor
- recent-window performance

### 5. Apply risk gates

Block trading and return `HOLD` if any of these fail:

- fewer than 20 trades for short-term strategy evaluation
- max drawdown above user threshold
- recent performance materially worse than full-sample performance
- one symbol dominates the whole strategy
- strategy depends on unsupported live data inputs

### 6. Produce decision

Allowed outputs:

- `BUY`
- `SELL`
- `REDUCE`
- `HOLD`

Output schema:

```json
{
  "strategy_candidate": "...",
  "backtest_summary": {},
  "risk_report": {},
  "trade_decision": "HOLD",
  "execution_plan": {}
}
```

### 7. Execution policy

- `research`: no orders, report only
- `paper`: simulate intended orders, record what would be sent
- `live`: require broker adapter + explicit user approval + risk gate pass

Without all three, do not place live orders.

## Guardrails

- hold-by-default
- no live trade on strategy creation alone
- no live trade from commit summaries alone
- no short selling unless covered short is explicitly enabled
- keep KR ETF / ETN typing explicit when uncertain

## Recommended Prompt Shape

Use this structure when driving the orchestrator:

```text
한국장 기준으로 [유니버스]에서 [전략 유형] 전략 후보를 만들고,
백테스트 후 리스크 게이트를 통과한 경우에만 paper decision을 내려줘.
매수 기준은 [조건], 매도 기준은 [조건], 최대 보유 종목 수는 [N],
기간은 [start]~[end], 기본값은 HOLD로 해줘.
```

## Deliverables

At the end of the run, always provide:

1. what strategy was built
2. why the signal exists
3. what the backtest showed
4. why the final decision is not or is actionable
5. what would be sent to paper/live execution next

## Minimal Runtime Example

Use this exact flow when the user asks for KR automated strategy generation:

```text
load_skill("kr-auto-trading-orchestrator")
load_skill("strategy-generate")
write_file("config.json", ...)
write_file("artifacts/symbol_scores.json", ...)
apply_signal_ranking_selection(
  path="config.json",
  ranking_path="artifacts/symbol_scores.json",
  max_positions=2,
  selection_reason="opening strength rank"
)
prepare_orchestrator_config(
  path="config.json",
  mode="paper",
  strategy_id="kr-opening-breakout",
  strategy_version="v1"
)
write_file("code/signal_engine.py", ...)
backtest(run_dir=...)
read_file("artifacts/trade_decision.json")
```
