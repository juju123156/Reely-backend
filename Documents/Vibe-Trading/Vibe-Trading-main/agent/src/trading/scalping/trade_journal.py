"""TradeJournal — 모든 거래 기록. 향후 백테스트 검증·전략 개선의 핵심."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradeRecord:
    """진입~청산 1사이클 전체 기록."""
    # 식별
    symbol: str
    side: str                  # "buy" | "sell"
    order_no: str
    reason: str                # entry_1, exit_tp1, exit_sl, etc.

    # 체결 정보
    expected_price: float
    fill_price: float
    qty: int
    commission: float
    tax: float

    # 슬리피지
    slippage_pct: float        # (fill - expected) / expected, 양수 = 불리

    # 진입 시점 신호 (진입 주문만 기록)
    score: float = 0.0
    exec_strength: float = 0.0
    ob_imbalance: float = 0.0
    vwap_gap: float = 0.0
    atr: float = 0.0
    vol_ratio: float = 0.0
    market_kosdaq_pct: float = 0.0
    regime: str = ""          # 진입 시 레짐 (백테스트 레짐별 성과 분석용)
    position_type: str = "intraday_scalp"
    change_pct_at_entry: float = 0.0
    exec_strength_30m: float = 0.0
    vi_count_60m: int = 0
    kosdaq_at_entry: float = 0.0
    trading_value_at_entry: float = 0.0
    overnight_exposure_pct: float = 0.0
    after_market_added: bool = False
    after_market_add_qty: int = 0
    after_market_add_price: float = 0.0
    after_market_order_status: str = ""
    gap_pct: float = 0.0
    exit_reason: str = ""
    holding_overnight: bool = False
    execution_venue: str = "krx"
    preferred_venue: str = "krx"
    actual_venue: str = "unknown"
    venue_policy: str = "krx_only"
    listing_market: str = "kosdaq"
    market_session: str = "krx_regular"
    krx_reference_price: float = 0.0
    nxt_reference_price: float = 0.0
    venue_price_gap: float = 0.0
    venue_liquidity_ratio: float = 0.0
    venue_spread: float = 0.0
    nxt_after_price: float = 0.0
    nxt_pre_price: float = 0.0
    nxt_after_volume: float = 0.0
    nxt_pre_volume: float = 0.0

    # 청산 시점 손익 (청산 주문만 기록)
    net_pnl: float = 0.0       # 실현 손익 (수수료·세금 차감)
    holding_secs: float = 0.0  # 보유 시간 (초)

    # 공통
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "symbol":            self.symbol,
            "side":              self.side,
            "order_no":          self.order_no,
            "reason":            self.reason,
            "expected_price":    round(self.expected_price, 0),
            "fill_price":        round(self.fill_price, 0),
            "qty":               self.qty,
            "commission":        round(self.commission, 0),
            "tax":               round(self.tax, 0),
            "slippage_pct":      round(self.slippage_pct * 100, 3),  # % 표시
            "score":             round(self.score, 1),
            "exec_strength":     round(self.exec_strength, 1),
            "ob_imbalance":      round(self.ob_imbalance, 3),
            "vwap_gap":          round(self.vwap_gap * 100, 3),      # % 표시
            "atr":               round(self.atr, 0),
            "vol_ratio":         round(self.vol_ratio, 2),
            "market_kosdaq_pct": round(self.market_kosdaq_pct * 100, 2),
            "regime":            self.regime,
            "position_type":      self.position_type,
            "change_pct_at_entry": round(self.change_pct_at_entry, 4),
            "exec_strength_30m":  round(self.exec_strength_30m, 1),
            "vi_count_60m":       self.vi_count_60m,
            "kosdaq_at_entry":    round(self.kosdaq_at_entry, 4),
            "trading_value_at_entry": round(self.trading_value_at_entry, 0),
            "overnight_exposure_pct": round(self.overnight_exposure_pct, 4),
            "after_market_added": self.after_market_added,
            "after_market_add_qty": self.after_market_add_qty,
            "after_market_add_price": round(self.after_market_add_price, 0),
            "after_market_order_status": self.after_market_order_status,
            "gap_pct":           round(self.gap_pct, 4),
            "exit_reason":       self.exit_reason or self.reason,
            "holding_overnight": self.holding_overnight,
            "execution_venue":   self.execution_venue,
            "preferred_venue":   self.preferred_venue,
            "actual_venue":      self.actual_venue,
            "venue_policy":      self.venue_policy,
            "listing_market":    self.listing_market,
            "market_session":    self.market_session,
            "krx_reference_price": round(self.krx_reference_price, 0),
            "nxt_reference_price": round(self.nxt_reference_price, 0),
            "venue_price_gap":   round(self.venue_price_gap, 4),
            "venue_liquidity_ratio": round(self.venue_liquidity_ratio, 4),
            "venue_spread":      round(self.venue_spread, 4),
            "nxt_after_price":   round(self.nxt_after_price, 0),
            "nxt_pre_price":     round(self.nxt_pre_price, 0),
            "nxt_after_volume":  round(self.nxt_after_volume, 0),
            "nxt_pre_volume":    round(self.nxt_pre_volume, 0),
            "net_pnl":           round(self.net_pnl, 0),
            "holding_secs":      round(self.holding_secs, 1),
            "ts":                self.ts,
        }


class TradeJournal:
    """인메모리 거래 저널. StateStore.log_trade()를 통해 영구 저장."""

    def __init__(self) -> None:
        self._records: list[TradeRecord] = []
        self._entry_ts: dict[str, float] = {}   # symbol → 진입 epoch

    def record_entry(
        self,
        symbol: str, order_no: str, fill_price: float,
        expected_price: float, qty: int,
        commission: float, slippage_pct: float,
        score: float, exec_strength: float, ob_imbalance: float,
        vwap_gap: float, atr: float, vol_ratio: float,
        market_kosdaq_pct: float,
        regime: str = "",
        position_type: str = "intraday_scalp",
        metadata: Optional[dict] = None,
    ) -> TradeRecord:
        metadata = metadata or {}
        self._entry_ts[symbol] = time.time()
        rec = TradeRecord(
            symbol=symbol, side="buy", order_no=order_no,
            reason="entry",
            expected_price=expected_price, fill_price=fill_price,
            qty=qty, commission=commission, tax=0.0,
            slippage_pct=slippage_pct,
            score=score, exec_strength=exec_strength,
            ob_imbalance=ob_imbalance, vwap_gap=vwap_gap,
            atr=atr, vol_ratio=vol_ratio,
            market_kosdaq_pct=market_kosdaq_pct,
            regime=regime,
            position_type=position_type,
            change_pct_at_entry=float(metadata.get("change_pct_at_entry") or 0),
            exec_strength_30m=float(metadata.get("exec_strength_30m") or 0),
            vi_count_60m=int(metadata.get("vi_count_60m") or 0),
            kosdaq_at_entry=float(metadata.get("kosdaq_at_entry") or 0),
            trading_value_at_entry=float(metadata.get("trading_value_at_entry") or 0),
            overnight_exposure_pct=float(metadata.get("overnight_exposure_pct") or 0),
            execution_venue=str(metadata.get("execution_venue") or "krx"),
            preferred_venue=str(metadata.get("preferred_venue") or "krx"),
            actual_venue=str(metadata.get("actual_venue") or "unknown"),
            venue_policy=str(metadata.get("venue_policy") or "krx_only"),
            listing_market=str(metadata.get("listing_market") or "kosdaq"),
            market_session=str(metadata.get("market_session") or "krx_regular"),
            krx_reference_price=float(metadata.get("krx_reference_price") or 0),
            nxt_reference_price=float(metadata.get("nxt_reference_price") or 0),
            venue_price_gap=float(metadata.get("venue_price_gap") or 0),
            venue_liquidity_ratio=float(metadata.get("venue_liquidity_ratio") or 0),
            venue_spread=float(metadata.get("venue_spread") or 0),
            nxt_after_price=float(metadata.get("nxt_after_price") or 0),
            nxt_pre_price=float(metadata.get("nxt_pre_price") or 0),
            nxt_after_volume=float(metadata.get("nxt_after_volume") or 0),
            nxt_pre_volume=float(metadata.get("nxt_pre_volume") or 0),
        )
        self._records.append(rec)
        return rec

    def record_exit(
        self,
        symbol: str, order_no: str, fill_price: float,
        expected_price: float, qty: int,
        commission: float, tax: float, slippage_pct: float,
        net_pnl: float, reason: str,
        position_type: str = "intraday_scalp",
        metadata: Optional[dict] = None,
    ) -> TradeRecord:
        metadata = metadata or {}
        entry_ts = self._entry_ts.pop(symbol, time.time())
        holding_secs = time.time() - entry_ts
        rec = TradeRecord(
            symbol=symbol, side="sell", order_no=order_no,
            reason=reason,
            expected_price=expected_price, fill_price=fill_price,
            qty=qty, commission=commission, tax=tax,
            slippage_pct=slippage_pct,
            net_pnl=net_pnl,
            holding_secs=holding_secs,
            position_type=position_type,
            gap_pct=float(metadata.get("gap_pct") or 0),
            exit_reason=str(metadata.get("exit_reason") or reason),
            holding_overnight=bool(metadata.get("holding_overnight") or False),
            after_market_added=bool(metadata.get("after_market_added") or False),
            after_market_add_qty=int(metadata.get("after_market_add_qty") or 0),
            after_market_add_price=float(metadata.get("after_market_add_price") or 0),
            after_market_order_status=str(metadata.get("after_market_order_status") or ""),
            execution_venue=str(metadata.get("execution_venue") or "krx"),
            preferred_venue=str(metadata.get("preferred_venue") or "krx"),
            actual_venue=str(metadata.get("actual_venue") or "unknown"),
            venue_policy=str(metadata.get("venue_policy") or "krx_only"),
            listing_market=str(metadata.get("listing_market") or "kosdaq"),
            market_session=str(metadata.get("market_session") or "krx_regular"),
            krx_reference_price=float(metadata.get("krx_reference_price") or 0),
            nxt_reference_price=float(metadata.get("nxt_reference_price") or 0),
            venue_price_gap=float(metadata.get("venue_price_gap") or 0),
            venue_liquidity_ratio=float(metadata.get("venue_liquidity_ratio") or 0),
            venue_spread=float(metadata.get("venue_spread") or 0),
            nxt_after_price=float(metadata.get("nxt_after_price") or 0),
            nxt_pre_price=float(metadata.get("nxt_pre_price") or 0),
            nxt_after_volume=float(metadata.get("nxt_after_volume") or 0),
            nxt_pre_volume=float(metadata.get("nxt_pre_volume") or 0),
        )
        self._records.append(rec)
        return rec

    def get_today(self) -> list[dict]:
        return [r.to_dict() for r in self._records]

    def regime_summary(self) -> dict:
        """레짐별 성과 분석 (백테스트 / 실시간 검증용)."""
        exits = [r for r in self._records if r.side == "sell"]
        entries = {r.order_no: r for r in self._records if r.side == "buy"}

        result: dict[str, dict] = {}
        for ex in exits:
            # 진입 레코드에서 regime 가져오기 (order_no 매칭)
            entry_regime = ""
            for e in self._records:
                if e.side == "buy" and e.symbol == ex.symbol:
                    entry_regime = e.regime
                    break
            regime_key = entry_regime or "unknown"

            if regime_key not in result:
                result[regime_key] = {"trades": 0, "wins": 0, "total_pnl": 0.0, "holding_secs": []}

            r = result[regime_key]
            r["trades"] += 1
            if ex.net_pnl > 0:
                r["wins"] += 1
            r["total_pnl"] += ex.net_pnl
            r["holding_secs"].append(ex.holding_secs)

        return {
            regime: {
                "trades":         v["trades"],
                "win_rate":       round(v["wins"] / v["trades"], 3) if v["trades"] else 0,
                "total_pnl":      round(v["total_pnl"]),
                "avg_holding":    round(sum(v["holding_secs"]) / len(v["holding_secs"]), 1) if v["holding_secs"] else 0,
            }
            for regime, v in result.items()
        }

    def summary(self) -> dict:
        exits = [r for r in self._records if r.side == "sell"]
        if not exits:
            return {"trades": 0}
        total_pnl   = sum(r.net_pnl for r in exits)
        wins        = [r for r in exits if r.net_pnl > 0]
        avg_holding = sum(r.holding_secs for r in exits) / len(exits)
        avg_slip    = sum(abs(r.slippage_pct) for r in exits) / len(exits)
        return {
            "trades":       len(exits),
            "win_rate":     round(len(wins) / len(exits), 3),
            "total_pnl":    round(total_pnl),
            "avg_holding_secs": round(avg_holding, 1),
            "avg_slippage_pct": round(avg_slip * 100, 3),
        }
