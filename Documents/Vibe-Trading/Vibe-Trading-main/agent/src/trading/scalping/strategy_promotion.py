"""Promotion gate for shadow-first intraday strategies."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class PromotionState(Enum):
    DISABLED = "disabled"
    SHADOW_ONLY = "shadow_only"
    DRY_RUN_LIVE = "dry_run_live"   # live 게이트 통과, FakeBroker 시뮬 주문
    SMALL_LIVE = "small_live"
    NORMAL_LIVE = "normal_live"
    PAUSED = "paused"


@dataclass(frozen=True)
class PromotionDecision:
    strategy: str
    state: PromotionState
    reason: str
    sample_count: int = 0
    net_expectancy: float = 0.0
    win_rate: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0


class StrategyPromotionGate:
    """Loads T+1 strategy-condition permissions from the latest promotion state."""

    DEFAULT_SHADOW_FIRST = {
        "opening_momentum",
        "shallow_pullback",
        "leader_only_shallow_pullback",
        "leader_only_shallow_pullback_near_miss",
        "vwap_reclaim",
        "momentum_continuation",
        "shadow_scan_immediate",
        "scan_immediate",
    }
    ALIASES = {
        "shallow_pullback": "leader_only_shallow_pullback",
        "leader_only_shallow_pullback_near_miss": "leader_only_shallow_pullback",
    }

    def __init__(self, state_path: str | Path = "data/strategy_promotion/current.json") -> None:
        self._state_path = Path(state_path)
        self._cache_mtime: float = -1.0
        self._states: dict[str, PromotionState] = {}
        self._promotion_candidates: set[str] = set()

    def state_for(self, strategy: str) -> PromotionState:
        self._load_if_needed()
        if strategy in self._states:
            return self._states[strategy]
        alias = self.ALIASES.get(strategy)
        if alias and alias in self._states:
            return self._states[alias]
        if strategy in self.DEFAULT_SHADOW_FIRST:
            return PromotionState.SHADOW_ONLY
        return PromotionState.SHADOW_ONLY

    def live_allowed(self, strategy: str) -> bool:
        return self.state_for(strategy) in {
            PromotionState.DRY_RUN_LIVE,
            PromotionState.SMALL_LIVE,
            PromotionState.NORMAL_LIVE,
        }

    def is_dry_run_live(self, strategy: str) -> bool:
        return self.state_for(strategy) == PromotionState.DRY_RUN_LIVE

    def is_promotion_candidate(self, strategy: str) -> bool:
        self._load_if_needed()
        resolved = self.ALIASES.get(strategy, strategy)
        return strategy in self._promotion_candidates or resolved in self._promotion_candidates

    def _load_if_needed(self) -> None:
        try:
            mtime = self._state_path.stat().st_mtime
        except FileNotFoundError:
            self._states = {}
            self._promotion_candidates = set()
            self._cache_mtime = -1.0
            return
        if mtime == self._cache_mtime:
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            self._states = {}
            self._promotion_candidates = set()
            self._cache_mtime = mtime
            return

        parsed: dict[str, PromotionState] = {}
        candidates: set[str] = set()

        # 구형 형식: {"states": {"strategy": "state_value"}}
        if "states" in payload and isinstance(payload["states"], dict):
            for strategy, state in payload["states"].items():
                try:
                    parsed[strategy] = PromotionState(str(state))
                except ValueError:
                    parsed[strategy] = PromotionState.SHADOW_ONLY
        else:
            # 신형 형식: {"strategy": {"promotion_state": ..., "promotion_candidate": bool, ...}}
            for key, val in payload.items():
                if key in {"generated_at", "effective_date", "decisions"}:
                    continue
                if isinstance(val, dict):
                    state_str = str(val.get("promotion_state") or val.get("state") or "shadow_only")
                    try:
                        parsed[key] = PromotionState(state_str)
                    except ValueError:
                        parsed[key] = PromotionState.SHADOW_ONLY
                    if bool(val.get("promotion_candidate")):
                        candidates.add(key)
                elif isinstance(val, str):
                    try:
                        parsed[key] = PromotionState(val)
                    except ValueError:
                        parsed[key] = PromotionState.SHADOW_ONLY

        self._states = parsed
        self._promotion_candidates = candidates
        self._cache_mtime = mtime


def _net_positive_with_margin(net: float, min_margin: float = 0.001) -> bool:
    """net expectancy가 cost 여유를 포함해 실질 양수인지 확인."""
    return net > min_margin


def decide_promotions(
    strategy_stats: dict[str, dict[str, Any]],
    current_gate: StrategyPromotionGate | None = None,
) -> list[PromotionDecision]:
    """shadow stats → next-day promotion decision.

    승격 경로: shadow_only → dry_run_live → small_live
    각 단계별 요건:
      - dry_run_live: 샘플 ≥30, net>0, win_rate≥0.40, avg_mae>-0.010
      - small_live:   샘플 ≥50, net>0.001 (cost margin), win_rate≥0.45, avg_mae>-0.006, mfe>mae 비율
    현 dry_run_live 전략은 small_live 조건 충족 시 small_live로 승격.
    """
    decisions: list[PromotionDecision] = []
    for strategy, stats in sorted(strategy_stats.items()):
        n = int(stats.get("sample_count") or 0)
        win_rate = float(stats.get("win_rate") or 0.0)
        avg_mfe = float(stats.get("avg_mfe_pct") or 0.0)
        avg_mae = float(stats.get("avg_mae_pct") or 0.0)
        net = float(stats.get("net_expectancy") or 0.0)
        mfe_10 = float(stats.get("mfe_1pct_hit_rate") or 0.0)
        mae_08 = float(stats.get("mae_minus_0_8pct_hit_rate") or 0.0)
        mfe_08 = float(stats.get("mfe_0_8pct_hit_rate") or 0.0)
        mfe_03_60s = float(stats.get("mfe_0_3pct_60s_hit_rate") or 0.0)
        fake_breakout = float(stats.get("fake_breakout_rate") or 1.0)

        current_state = (
            current_gate.state_for(strategy)
            if current_gate is not None
            else PromotionState.SHADOW_ONLY
        )

        state = PromotionState.SHADOW_ONLY
        reason = "insufficient_shadow_evidence"

        if strategy in {"leader_only_shallow_pullback", "leader_only_shallow_pullback_near_miss", "shallow_pullback"}:
            small_live_ok = (
                n >= 50
                and win_rate >= 0.45
                and avg_mfe >= 0.010
                and avg_mae >= -0.006
                and mfe_10 > mae_08
                and _net_positive_with_margin(net)
            )
            dry_run_ok = n >= 30 and net > 0 and win_rate >= 0.40 and avg_mae >= -0.010
            if small_live_ok and current_state == PromotionState.DRY_RUN_LIVE:
                state = PromotionState.SMALL_LIVE
                reason = "leader_shallow_dry_run_passed_to_small_live"
            elif small_live_ok:
                state = PromotionState.SMALL_LIVE
                reason = "leader_shallow_shadow_passed"
            elif dry_run_ok:
                state = PromotionState.DRY_RUN_LIVE
                reason = "leader_shallow_dry_run_candidate"
            else:
                reason = f"need_more_evidence (n={n}/50 net={net:.4f} wr={win_rate:.2f})"

        elif strategy == "vwap_reclaim":
            small_live_ok = (
                n >= 50
                and mfe_08 > mae_08
                and avg_mae >= -0.006
                and _net_positive_with_margin(net)
            )
            dry_run_ok = n >= 30 and net > 0 and win_rate >= 0.40 and avg_mae >= -0.010
            if small_live_ok and current_state == PromotionState.DRY_RUN_LIVE:
                state = PromotionState.SMALL_LIVE
                reason = "vwap_reclaim_dry_run_passed"
            elif small_live_ok:
                state = PromotionState.SMALL_LIVE
                reason = "vwap_reclaim_shadow_passed"
            elif dry_run_ok:
                state = PromotionState.DRY_RUN_LIVE
                reason = "vwap_reclaim_dry_run_candidate"
            else:
                reason = f"need_more_evidence (n={n}/50 net={net:.4f})"

        elif strategy == "momentum_continuation":
            small_live_ok = (
                n >= 100
                and fake_breakout <= 0.55
                and mfe_03_60s > mae_08
                and _net_positive_with_margin(net)
            )
            dry_run_ok = n >= 50 and net > 0 and fake_breakout <= 0.65 and avg_mae >= -0.010
            if small_live_ok and current_state == PromotionState.DRY_RUN_LIVE:
                state = PromotionState.SMALL_LIVE
                reason = "momentum_continuation_dry_run_passed"
            elif small_live_ok:
                state = PromotionState.SMALL_LIVE
                reason = "momentum_continuation_shadow_passed"
            elif dry_run_ok:
                state = PromotionState.DRY_RUN_LIVE
                reason = "momentum_continuation_dry_run_candidate"
            else:
                reason = f"need_more_evidence (n={n}/100 fake_breakout={fake_breakout:.2f})"

        elif strategy == "opening_momentum":
            small_live_ok = (
                n >= 50
                and _net_positive_with_margin(net)
                and fake_breakout <= 0.55
                and win_rate >= 0.45
            )
            dry_run_ok = n >= 30 and net > 0 and fake_breakout <= 0.65
            if small_live_ok and current_state == PromotionState.DRY_RUN_LIVE:
                state = PromotionState.SMALL_LIVE
                reason = "opening_momentum_dry_run_passed"
            elif small_live_ok:
                state = PromotionState.SMALL_LIVE
                reason = "opening_momentum_shadow_passed"
            elif dry_run_ok:
                state = PromotionState.DRY_RUN_LIVE
                reason = "opening_momentum_dry_run_candidate"
            else:
                reason = f"need_more_evidence (n={n}/50 net={net:.4f})"

        elif strategy == "shadow_scan_immediate":
            small_live_ok = n >= 100 and _net_positive_with_margin(net)
            dry_run_ok = n >= 50 and net > 0
            if small_live_ok and current_state == PromotionState.DRY_RUN_LIVE:
                state = PromotionState.SMALL_LIVE
                reason = "scan_immediate_dry_run_passed"
            elif small_live_ok:
                state = PromotionState.SMALL_LIVE
                reason = "scan_immediate_shadow_passed"
            elif dry_run_ok:
                state = PromotionState.DRY_RUN_LIVE
                reason = "scan_immediate_dry_run_candidate"
            else:
                reason = f"need_more_evidence (n={n}/100)"

        decisions.append(PromotionDecision(
            strategy=strategy,
            state=state,
            reason=reason,
            sample_count=n,
            net_expectancy=net,
            win_rate=win_rate,
            avg_mfe=avg_mfe,
            avg_mae=avg_mae,
        ))
    return decisions


def write_promotion_state(
    decisions: list[PromotionDecision],
    *,
    base_dir: str | Path = "data/strategy_promotion",
    report_date: date | None = None,
    preserve_candidates: StrategyPromotionGate | None = None,
) -> Path:
    """결정 목록을 신형 rich JSON 포맷으로 기록한다.

    신형 포맷: strategy 키 → {"promotion_state": ..., "promotion_candidate": bool, ...}
    기존 코드 호환을 위해 최상위 "states" 키도 함께 기록한다.
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    report_date = report_date or date.today()

    # 기존 current.json에서 promotion_candidate 플래그 보존
    existing_candidates: set[str] = set()
    if preserve_candidates is not None:
        preserve_candidates._load_if_needed()
        existing_candidates = preserve_candidates._promotion_candidates

    strategy_entries: dict[str, Any] = {}
    for d in decisions:
        is_candidate = d.strategy in existing_candidates or d.state in {
            PromotionState.DRY_RUN_LIVE, PromotionState.SMALL_LIVE, PromotionState.NORMAL_LIVE,
        }
        strategy_entries[d.strategy] = {
            "promotion_state": d.state.value,
            "promotion_candidate": is_candidate,
            "reason": d.reason,
            "sample_count": d.sample_count,
            "net_expectancy": round(d.net_expectancy, 6),
            "win_rate": round(d.win_rate, 4),
            "avg_mfe": round(d.avg_mfe, 6),
            "avg_mae": round(d.avg_mae, 6),
        }

    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "effective_date": report_date.isoformat(),
        # 구형 호환 필드
        "states": {d.strategy: d.state.value for d in decisions},
        **strategy_entries,
    }
    dated = base / f"{report_date.isoformat()}.json"
    current = base / "current.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    dated.write_text(text + "\n", encoding="utf-8")
    current.write_text(text + "\n", encoding="utf-8")
    return current
