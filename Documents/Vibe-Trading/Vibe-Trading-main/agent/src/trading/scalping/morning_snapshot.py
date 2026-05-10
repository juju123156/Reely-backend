"""MorningSnapshot — 오전 강세 종목 자동 태깅 (점심 전략 백테스팅 데이터 축적)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "morning_snapshots"

# 점심 후보 판정 기준
_MIN_CHANGE_PCT = 0.08              # 오전 상승률 8%+
_MIN_TRADING_VALUE = 30_000_000_000  # 거래대금 300억+


@dataclass
class MorningSnapshot:
    date: str                        # YYYY-MM-DD
    symbol: str
    name: str
    change_pct: float                # 전일 대비 등락률 (소수)
    morning_high: float              # 오전 고점
    price_now: float                 # 스냅샷 시점 현재가
    trading_value: float             # 누적 거래대금
    avg_exec_strength: float         # 오전 평균 체결강도
    vol_ratio: float                 # 전일 동시간 대비 거래량 배율
    vwap: float                      # 스냅샷 시점 VWAP
    above_vwap: bool                 # 현재가 >= VWAP
    vwap_gap_pct: float              # (현재가 - VWAP) / VWAP
    atr: float                       # 장 시작 전 ATR
    is_lunch_candidate: bool         # 점심 전략 후보 여부
    fail_reasons: list               # 후보 미달 사유
    regime: str                      # 스냅샷 시점 레짐
    snapshot_ts: str                 # ISO 타임스탬프


class MorningSnapshotStore:
    """날짜별 JSONL 파일로 오전 스냅샷 저장."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._dir = data_dir or _DATA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def save_all(self, snapshots: list[MorningSnapshot]) -> None:
        if not snapshots:
            return
        today = date.today().isoformat()
        path = self._dir / f"{today}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for snap in snapshots:
                f.write(json.dumps(snap.__dict__, ensure_ascii=False) + "\n")
        logger.info(
            "MorningSnapshotStore: saved %d snapshots → %s",
            len(snapshots), path,
        )

    @staticmethod
    def build_snapshot(
        *,
        symbol: str,
        name: str,
        change_pct: float,
        morning_high: float,
        price_now: float,
        trading_value: float,
        exec_samples: list,
        vol_ratio: float,
        vwap: float,
        atr: float,
        regime: str,
    ) -> MorningSnapshot:
        above_vwap = price_now >= vwap > 0
        vwap_gap_pct = (price_now - vwap) / vwap if vwap > 0 else 0.0
        avg_exec = sum(exec_samples) / len(exec_samples) if exec_samples else 0.0

        fail_reasons: list[str] = []
        if change_pct < _MIN_CHANGE_PCT:
            fail_reasons.append(f"change_pct={change_pct:.1%}<{_MIN_CHANGE_PCT:.0%}")
        if trading_value < _MIN_TRADING_VALUE:
            fail_reasons.append(f"trading_value={trading_value / 1e8:.0f}억<300억")
        if not above_vwap:
            fail_reasons.append("below_vwap")

        return MorningSnapshot(
            date=date.today().isoformat(),
            symbol=symbol,
            name=name,
            change_pct=round(change_pct, 4),
            morning_high=morning_high,
            price_now=price_now,
            trading_value=trading_value,
            avg_exec_strength=round(avg_exec, 1),
            vol_ratio=round(vol_ratio, 2),
            vwap=round(vwap, 2),
            above_vwap=above_vwap,
            vwap_gap_pct=round(vwap_gap_pct, 4),
            atr=round(atr, 2),
            is_lunch_candidate=len(fail_reasons) == 0,
            fail_reasons=fail_reasons,
            regime=regime,
            snapshot_ts=datetime.now().isoformat(timespec="seconds"),
        )
