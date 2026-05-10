"""컴포넌트 간 이벤트 데이터클래스."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .position_type import PositionType
from .venue import ExecutionVenue, ListingMarket, MarketSession, VenuePolicy


class EventType(str, Enum):
    TICK           = "tick"
    SIGNAL         = "signal"
    ORDER_REQUEST  = "order_request"
    ORDER_FILL     = "order_fill"
    ORDER_CANCEL   = "order_cancel"
    POSITION_OPEN  = "position_open"
    POSITION_CLOSE = "position_close"
    RISK_BREACH    = "risk_breach"
    KILL_SWITCH    = "kill_switch"
    VI_DETECTED    = "vi_detected"
    VI_CLEARED     = "vi_cleared"


@dataclass
class TickEvent:
    symbol: str
    price: float
    buy_vol_total: float   # SHNU_CNTG_SMTN  — 당일 누적 매수 체결량
    sell_vol_total: float  # SELN_CNTG_SMTN  — 당일 누적 매도 체결량
    bid_qty: float         # TOTAL_BIDP_RSQN — 총 매수호가 잔량
    ask_qty: float         # TOTAL_ASKP_RSQN — 총 매도호가 잔량
    tick_vol: float        # CNTG_VOL        — 해당 틱 체결량
    acml_vol: float        # ACML_VOL        — 당일 누적 거래량 (VWAP용)
    acml_tr_pbmn: float    # ACML_TR_PBMN    — 당일 누적 거래대금 (VWAP용)
    time_str: str          # STCK_CNTG_HOUR  — HHMMSS
    is_vi: bool = False    # TRHT_YN == "Y"
    ask1_price: float = 0.0  # ASKP1 — 매도1호가 (스프레드 체크용)
    bid1_price: float = 0.0  # BIDP1 — 매수1호가 (스프레드 체크용)
    ask1_qty: float = 0.0
    bid1_qty: float = 0.0
    ask2_price: float = 0.0
    ask2_qty: float = 0.0
    bid2_price: float = 0.0
    bid2_qty: float = 0.0
    ask3_price: float = 0.0
    ask3_qty: float = 0.0
    bid3_price: float = 0.0
    bid3_qty: float = 0.0
    ask4_price: float = 0.0
    ask4_qty: float = 0.0
    bid4_price: float = 0.0
    bid4_qty: float = 0.0
    ask5_price: float = 0.0
    ask5_qty: float = 0.0
    bid5_price: float = 0.0
    bid5_qty: float = 0.0
    ask6_price: float = 0.0
    ask6_qty: float = 0.0
    bid6_price: float = 0.0
    bid6_qty: float = 0.0
    ask7_price: float = 0.0
    ask7_qty: float = 0.0
    bid7_price: float = 0.0
    bid7_qty: float = 0.0
    ask8_price: float = 0.0
    ask8_qty: float = 0.0
    bid8_price: float = 0.0
    bid8_qty: float = 0.0
    ask9_price: float = 0.0
    ask9_qty: float = 0.0
    bid9_price: float = 0.0
    bid9_qty: float = 0.0
    ask10_price: float = 0.0
    ask10_qty: float = 0.0
    bid10_price: float = 0.0
    bid10_qty: float = 0.0
    orderbook_source_ts: float = 0.0
    orderbook_received_ts: float = 0.0
    orderbook_age_sec: float = 999.0
    depth_levels_available: int = 1
    orderbook_stale: bool = True
    orderbook_quality: str = "fallback"
    invalid_orderbook: bool = False
    orderbook_invalid_reason: str = ""
    ts: datetime = field(default_factory=datetime.now)


@dataclass
class SignalEvent:
    symbol: str
    score: float
    action: str            # "enter_watch" | "enter_now" | "pyramid" | "exit"
    reason: str
    exec_strength: float
    ob_imbalance: float
    vwap_gap: float        # (price - vwap) / vwap
    atr: float
    price: float
    ts: datetime = field(default_factory=datetime.now)


@dataclass
class OrderRequest:
    symbol: str
    side: str              # "buy" | "sell"
    qty: int
    price: float           # 0 = 시장가
    order_type: str        # "limit" | "market"
    reason: str            # "entry_1" | "entry_2" | "exit_tp1" | "exit_tp2" | "exit_sl" | "exit_trail" | "exit_time" | "kill_switch"
    ref_id: str = ""       # position id 연결
    market: str = "KOSDAQ" # "KOSDAQ" | "KOSPI" — 세금 계산 및 호가단위 보정용
    position_type: PositionType = PositionType.INTRADAY_SCALP
    order_session: str = ""       # "regular" | "after_market" | "next_open"
    ord_dvsn_override: Optional[str] = None
    listing_market: ListingMarket = ListingMarket.KOSDAQ
    execution_venue: ExecutionVenue = ExecutionVenue.KRX
    preferred_venue: ExecutionVenue = ExecutionVenue.KRX
    actual_venue: ExecutionVenue = ExecutionVenue.UNKNOWN
    venue_policy: VenuePolicy = VenuePolicy.KRX_ONLY
    market_session: MarketSession = MarketSession.KRX_REGULAR


@dataclass
class FillEvent:
    order_no: str
    symbol: str
    side: str
    filled_qty: int
    fill_price: float
    commission: float
    tax: float
    reason: str = ""       # OrderRequest.reason 전파
    listing_market: ListingMarket = ListingMarket.KOSDAQ
    execution_venue: ExecutionVenue = ExecutionVenue.KRX
    preferred_venue: ExecutionVenue = ExecutionVenue.KRX
    actual_venue: ExecutionVenue = ExecutionVenue.UNKNOWN
    venue_policy: VenuePolicy = VenuePolicy.KRX_ONLY
    market_session: MarketSession = MarketSession.KRX_REGULAR
    ts: datetime = field(default_factory=datetime.now)


@dataclass
class RiskBreachEvent:
    reason: str            # "daily_loss" | "consecutive_loss" | "market_halt" | "kill_switch"
    detail: str = ""
    ts: datetime = field(default_factory=datetime.now)
