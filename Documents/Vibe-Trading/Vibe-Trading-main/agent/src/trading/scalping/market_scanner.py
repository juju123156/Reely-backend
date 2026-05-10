"""MarketScanner — 거래대금 상위 종목 필터링 + ATR 캐싱."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Optional

from .constants import (
    MIN_TRADING_VALUE, MIN_PRICE,
    MAX_OPEN_GAP_PCT, MAX_CHANGE_NEAR_LIMIT,
    MIN_CHANGE_PCT, MAX_CHANGE_PCT,
    MIN_EXEC_STRENGTH, SCAN_TOP_N,
    ATR_CANDLE_INTERVAL, ATR_CANDLE_COUNT,
    KOSDAQ_HALT_THRESHOLD,
    SCAN_API_TIMEOUT_SEC, INDEX_API_TIMEOUT_SEC,
    ETF_NAME_PREFIXES,
    REIT_NAME_KEYWORDS,
)
from .leader_rotation import LeaderRotationEngine
from .vwap import ATRState, Candle

logger = logging.getLogger(__name__)

# 코스닥 지수 종목코드 (KIS get_quote 사용)
_KOSDAQ_INDEX_CODE = "Q"   # market_code 파라미터


@dataclass
class SymbolCandidate:
    symbol: str
    name: str
    price: float
    change_pct: float         # 전일 대비 등락률 (소수, 예: 0.05 = +5%)
    trading_value: float      # 당일 누적 거래대금 (원)
    volume: float             # 당일 누적 거래량
    exec_strength: float      # 체결강도 근사값
    market: str = "KOSDAQ"
    is_vi: bool = False
    is_managed: bool = False             # 관리종목 여부
    is_warning: bool = False             # 경고종목 여부
    is_investment_caution: bool = False  # 투자주의 종목
    is_investment_warning: bool = False  # 투자경고 종목
    is_investment_danger: bool = False   # 투자위험 종목
    is_short_term_overheated: bool = False  # 단기과열 종목
    is_trading_halted: bool = False      # 거래정지 종목
    is_delisting_trade: bool = False     # 정리매매 종목
    is_etf: bool = False                 # ETF 여부
    is_etn: bool = False                 # ETN 여부
    is_spac: bool = False                # 스팩(SPAC) 여부
    open_gap_pct: float = 0.0            # 시가 갭 (시가/전일종가 - 1), 갭업 필터용
    atr: float = 0.0                     # 장 시작 전 ATR 캐싱
    prev_same_time_vol: float = 0.0      # 전일 동시간 거래량 (vol_ratio 계산용)
    leader_rank: int = 999
    leader_score: float = 0.0

    @property
    def vol_ratio(self) -> float:
        """현재 거래량 / 전일 동시간 거래량."""
        if self.prev_same_time_vol <= 0:
            return 0.0
        return self.volume / self.prev_same_time_vol


class MarketScanner:
    """
    역할:
    - 장 시작 전: top_n 종목의 5분봉 ATR 계산 + 전일 거래량 캐싱
    - 장중: run_scan() 호출 시 거래대금 상위 → 필터 → 후보 리스트 반환
    - KOSDAQ 지수 모니터링 → -1.5% 이하면 빈 리스트 반환

    실전 주의:
    - KIS API rate limit: 초당 1회 → top_n=30이면 최소 30초 소요
    - get_volume_ranking()은 실전용 API (모의투자에서는 동일하게 호출 가능)
    - exec_strength는 get_volume_ranking()의 ntby_cntg_csnu(순매수체결건수)로 근사
      → 정확한 값은 get_execution_detail()로 개별 조회 필요
    - 장 시작 30분(09:00~09:30)은 거래대금 순위가 불안정 → 09:30 이후 신뢰
    """

    def __init__(self, adapter: Any, env: str = "demo") -> None:
        self._adapter = adapter
        self._env = env
        self._atr_cache: dict[str, ATRState] = {}         # symbol → ATRState
        self._prev_vol_cache: dict[str, float] = {}       # symbol → 전일 동시간 거래량
        self._kosdaq_change_pct: float = 0.0
        self._last_scan_date: str = ""
        self._last_scan_had_data: bool = True             # False when volume ranking returns empty (API error)
        self._last_scan_source_status: str = "init"
        self._last_scan_latency_ms: int = 0
        self._last_raw_count: int = 0
        self._last_after_etf_filter_count: int = 0
        self._last_reject_counts: dict[str, int] = {}
        self._last_valid_scan_at: float = 0.0
        self._consecutive_scan_failures: int = 0
        self._leader_engine = LeaderRotationEngine()

    # ── 장 시작 전 준비 (08:50~09:00 에 호출) ────────────────────────────────

    async def prepare(self, symbols: Optional[list[str]] = None) -> None:
        """ATR + 전일 거래량 캐싱. 장 시작 전 1회 호출."""
        today = date.today().isoformat()
        if self._last_scan_date == today:
            return  # 이미 오늘 준비 완료

        logger.info("MarketScanner.prepare() start")
        loop = asyncio.get_event_loop()

        # top_n 종목 가져오기 (symbols가 없으면 전체 스캔 대상)
        target_symbols = symbols
        if not target_symbols:
            try:
                rank = await loop.run_in_executor(
                    None,
                    lambda: self._adapter.get_volume_ranking(top_n=SCAN_TOP_N, env_dv=self._env),
                )
                target_symbols = [item["symbol"] for item in rank.get("items") or []]
            except Exception as exc:
                logger.warning("prepare: volume_ranking failed: %s", exc)
                target_symbols = []

        # 각 종목 ATR + 전일 거래량 캐싱 (rate limit 고려 0.2초 간격)
        for sym in target_symbols:
            await self._cache_atr(sym, loop)
            await asyncio.sleep(0.2)

        self._last_scan_date = today
        logger.info("MarketScanner.prepare() done: %d symbols cached", len(target_symbols))

    # ── 메인 스캔 ────────────────────────────────────────────────────────────

    async def run_scan(self, whitelist: Optional[list[str]] = None) -> list[SymbolCandidate]:
        """
        거래대금 상위 → 필터 → 후보 리스트 반환.
        whitelist 지정 시 해당 종목만 통과 (KOSPI_DEFENSIVE 유니버스 제한 등).
        시장 조건 불량 시 빈 리스트.
        """
        loop = asyncio.get_event_loop()

        # KOSDAQ 지수 갱신
        await self._update_kosdaq(loop)
        if self._kosdaq_change_pct <= KOSDAQ_HALT_THRESHOLD:
            logger.warning(
                "Market halt: KOSDAQ %.1f%% <= %.1f%%",
                self._kosdaq_change_pct * 100, KOSDAQ_HALT_THRESHOLD * 100,
            )
            return []

        # 거래대금 상위 조회
        started = time.monotonic()
        try:
            rank_result = await asyncio.wait_for(loop.run_in_executor(
                None,
                lambda: self._adapter.get_volume_ranking(top_n=SCAN_TOP_N, env_dv=self._env),
            ), timeout=SCAN_API_TIMEOUT_SEC)
            self._last_scan_latency_ms = int((time.monotonic() - started) * 1000)
        except asyncio.TimeoutError:
            self._last_scan_had_data = False
            self._last_scan_source_status = "api_timeout"
            self._last_scan_latency_ms = int((time.monotonic() - started) * 1000)
            self._consecutive_scan_failures += 1
            logger.warning(
                "[MarketScanner] raw_count=0 passed_count=0 source_status=api_timeout "
                "api_latency_ms=%d last_valid_scan_age_sec=%d failures=%d",
                self._last_scan_latency_ms, self.last_valid_scan_age_sec,
                self._consecutive_scan_failures,
            )
            return []
        except Exception as exc:
            self._last_scan_had_data = False
            self._last_scan_source_status = "api_error"
            self._last_scan_latency_ms = int((time.monotonic() - started) * 1000)
            self._consecutive_scan_failures += 1
            logger.warning(
                "[MarketScanner] raw_count=0 passed_count=0 source_status=api_error "
                "api_latency_ms=%d last_valid_scan_age_sec=%d failures=%d error=%s",
                self._last_scan_latency_ms, self.last_valid_scan_age_sec,
                self._consecutive_scan_failures, exc,
            )
            return []

        items = rank_result.get("items") or []
        self._last_raw_count = len(items)
        reject_counts: dict[str, int] = {}
        self._last_scan_had_data = len(items) > 0
        if items:
            self._last_scan_source_status = "ok"
            self._last_valid_scan_at = time.time()
            self._consecutive_scan_failures = 0
        else:
            self._last_scan_source_status = "api_empty"
            self._consecutive_scan_failures += 1
        candidates: list[SymbolCandidate] = []
        after_etf_filter_count = 0

        for item in items:
            symbol = item.get("symbol") or ""
            if not symbol:
                continue

            price = float(item.get("price") or 0)
            open_price = float(item.get("open_price") or item.get("stck_oprc") or 0)
            prev_close = float(item.get("prev_close") or item.get("stck_prdy_clpr") or 0)
            open_gap = (open_price / prev_close - 1.0) if open_price > 0 and prev_close > 0 else 0.0

            candidate = SymbolCandidate(
                symbol=symbol,
                name=item.get("name") or "",
                price=price,
                change_pct=float(item.get("change_rate") or 0),
                trading_value=float(item.get("trading_value") or 0),
                volume=float(item.get("volume") or 0),
                exec_strength=float(item.get("exec_strength") or 0),
                is_managed=bool(item.get("is_managed") or False),
                is_warning=bool(item.get("is_warning") or False),
                is_investment_caution=bool(item.get("is_investment_caution") or False),
                is_investment_warning=bool(item.get("is_investment_warning") or False),
                is_investment_danger=bool(item.get("is_investment_danger") or False),
                is_short_term_overheated=bool(item.get("is_short_term_overheated") or False),
                is_trading_halted=bool(item.get("is_trading_halted") or False),
                is_delisting_trade=bool(item.get("is_delisting_trade") or False),
                is_etf=bool(item.get("is_etf") or False),
                is_etn=bool(item.get("is_etn") or False),
                is_spac=bool(item.get("is_spac") or False),
                open_gap_pct=open_gap,
                atr=self._atr_cache.get(symbol, ATRState()).atr,
                prev_same_time_vol=self._prev_vol_cache.get(symbol, 0.0),
            )

            reject_reason = self._filter_reject_reason(candidate)
            if reject_reason not in {"excluded_security_type", "excluded_etf_name", "excluded_reit_name", "preferred_share"}:
                after_etf_filter_count += 1
            if whitelist and symbol not in whitelist:
                continue
            if reject_reason:
                reject_counts[reject_reason] = reject_counts.get(reject_reason, 0) + 1
            else:
                candidates.append(candidate)
        self._last_after_etf_filter_count = after_etf_filter_count
        self._last_reject_counts = reject_counts

        leader_profiles = self._leader_engine.rank(candidates)
        for c in candidates:
            profile = leader_profiles.get(c.symbol)
            if profile:
                c.leader_rank = profile.leader_rank
                c.leader_score = profile.leader_score

        status = "filtered_out" if items and not candidates else self._last_scan_source_status
        logger.info("MarketScanner: %d / %d passed filter", len(candidates), len(items))
        logger.info(
            "[MarketScanner] raw_count=%d passed_count=%d source_status=%s "
            "api_latency_ms=%d last_valid_scan_age_sec=%d failures=%d",
            len(items), len(candidates), status,
            self._last_scan_latency_ms, self.last_valid_scan_age_sec,
            self._consecutive_scan_failures,
        )
        return candidates

    # ── 개별 종목 실시간 체결강도 보강 (선택적) ──────────────────────────────

    async def enrich_exec_strength(self, symbol: str) -> float:
        """get_execution_detail()로 정확한 체결강도 조회."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._adapter.get_execution_detail(symbol, env_dv=self._env),
            )
            if result.get("status") == "ok":
                buy = float(result.get("buy_vol_total") or 0)
                sell = float(result.get("sell_vol_total") or 0)
                total = buy + sell
                if total > 0:
                    return buy / total * 200.0   # 100 기준 정규화
        except Exception as exc:
            logger.debug("enrich_exec_strength %s: %s", symbol, exc)
        return 0.0

    # ── 지수 감시 루프 전용 ───────────────────────────────────────────────────

    async def update_kosdaq_index(self) -> float:
        """KOSDAQ 지수 등락률 즉시 갱신 후 반환. 지수 전용 루프에서 1초 간격 호출."""
        loop = asyncio.get_event_loop()
        await self._update_kosdaq(loop)
        return self._kosdaq_change_pct

    # ── ATR 노출 (SignalEngine 주입용) ───────────────────────────────────────

    def get_atr(self, symbol: str) -> ATRState:
        return self._atr_cache.get(symbol, ATRState())

    @property
    def kosdaq_change_pct(self) -> float:
        return self._kosdaq_change_pct

    @property
    def last_scan_had_data(self) -> bool:
        """False when volume ranking returned empty (API rate-limit/error) — skip regime update."""
        return self._last_scan_had_data

    # ── 필터 ─────────────────────────────────────────────────────────────────

    def _passes_filter(self, c: SymbolCandidate) -> bool:
        return self._filter_reject_reason(c) == ""

    def _filter_reject_reason(self, c: SymbolCandidate) -> str:
        if c.price < MIN_PRICE:
            return "price_below_min"
        if c.trading_value < MIN_TRADING_VALUE:
            return "liquidity_below_min"
        if c.change_pct < MIN_CHANGE_PCT or c.change_pct > MAX_CHANGE_PCT:
            return "fail_change_pct"
        # 상한가 근접 제외 (+20% 이상)
        if c.change_pct >= MAX_CHANGE_NEAR_LIMIT:
            return "near_upper_limit"
        # 갭업 제외 — API에서 open_gap_pct를 제공하는 경우만 적용
        if c.open_gap_pct > 0 and c.open_gap_pct >= MAX_OPEN_GAP_PCT:
            return "open_gap_too_high"
        if c.is_vi:
            return "vi_active"
        if c.is_trading_halted:
            return "trading_halted"
        if c.is_delisting_trade:
            return "delisting_trade"
        # ETF / ETN / SPAC 제외 — 스캘핑 전략 비적합
        if c.is_etf or c.is_etn or c.is_spac:
            return "excluded_security_type"
        if self._looks_like_etf_name(c.name):
            return "excluded_etf_name"
        if self._looks_like_reit_name(c.name):
            return "excluded_reit_name"
        # 투자주의 이상 등급 제외
        if c.is_investment_caution or c.is_investment_warning or c.is_investment_danger:
            return "investment_warning"
        if c.is_short_term_overheated:
            return "short_term_overheated"
        # 관리종목 / 경고종목 제외
        if c.is_managed or c.is_warning:
            return "managed_or_warning"
        # 우선주 제외 (심볼 코드 마지막 자리가 '0'이 아닌 경우)
        if self._is_preferred_share(c.symbol):
            return "preferred_share"
        return ""

    @staticmethod
    def _is_preferred_share(symbol: str) -> bool:
        """우선주 여부 — 6자리 코드 마지막 자리가 '0'이 아니면 우선주로 간주."""
        return len(symbol) == 6 and symbol[-1] != '0'

    @staticmethod
    def _looks_like_etf_name(name: str) -> bool:
        clean = (name or "").upper().strip()
        return any(clean.startswith(prefix) for prefix in ETF_NAME_PREFIXES)

    @staticmethod
    def _looks_like_reit_name(name: str) -> bool:
        clean = (name or "").upper().strip()
        return any(keyword.upper() in clean for keyword in REIT_NAME_KEYWORDS)

    # ── ATR 캐싱 ─────────────────────────────────────────────────────────────

    async def _cache_atr(self, symbol: str, loop: asyncio.AbstractEventLoop) -> None:
        """5분봉 ATR_CANDLE_COUNT개를 가져와서 ATR 계산 후 캐싱."""
        from datetime import datetime, timedelta
        now = datetime.now()
        end = now.strftime("%H%M%S")
        # 장 시작 전이면 09:00 기준
        start_dt = (now - timedelta(hours=5)).replace(hour=9, minute=0, second=0)
        start = start_dt.strftime("%H%M%S")

        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._adapter.get_intraday_bars(
                    symbol, interval=ATR_CANDLE_INTERVAL,
                    start=start, end=end,
                    env_dv=self._env,
                ),
            )
            if result.get("status") == "ok":
                bars = result.get("bars") or []
                if not bars:
                    return
                atr_state = ATRState()
                candles = [
                    Candle(
                        high=float(b.get("high") or b.get("h") or 0),
                        low=float(b.get("low") or b.get("l") or 0),
                        close=float(b.get("close") or b.get("c") or 0),
                    )
                    for b in bars[-ATR_CANDLE_COUNT:]
                ]
                atr_state.bulk_load(candles)
                self._atr_cache[symbol] = atr_state

                # 전일 동시간 거래량 — 마지막 캔들 이전 동일 시간대 거래량으로 근사
                # 간단하게: 전체 평균 거래량 × 현재 경과 비율
                total_vol = sum(float(b.get("volume") or b.get("v") or 0) for b in bars)
                self._prev_vol_cache[symbol] = total_vol / max(len(bars), 1)

                logger.debug("ATR cached: %s atr=%.0f", symbol, atr_state.atr)
        except Exception as exc:
            logger.debug("_cache_atr %s: %s", symbol, exc)

    async def _update_kosdaq(self, loop: asyncio.AbstractEventLoop) -> None:
        """KOSDAQ 지수 등락률 갱신."""
        try:
            result = await asyncio.wait_for(loop.run_in_executor(
                None,
                lambda: self._adapter.get_quote("U001", market_code="U", env_dv=self._env),
            ), timeout=INDEX_API_TIMEOUT_SEC)
            if result.get("status") == "ok":
                rate = float((result.get("quote") or {}).get("change_rate") or 0)
                self._kosdaq_change_pct = rate / 100.0
        except asyncio.TimeoutError:
            logger.debug("_update_kosdaq timeout after %.1fs", INDEX_API_TIMEOUT_SEC)
        except Exception as exc:
            logger.debug("_update_kosdaq: %s", exc)

    @property
    def last_scan_source_status(self) -> str:
        return self._last_scan_source_status

    @property
    def last_scan_latency_ms(self) -> int:
        return self._last_scan_latency_ms

    @property
    def last_valid_scan_age_sec(self) -> int:
        if self._last_valid_scan_at <= 0:
            return 999999
        return max(0, int(time.time() - self._last_valid_scan_at))

    @property
    def consecutive_scan_failures(self) -> int:
        return self._consecutive_scan_failures

    @property
    def last_raw_count(self) -> int:
        return self._last_raw_count

    @property
    def last_after_etf_filter_count(self) -> int:
        return self._last_after_etf_filter_count

    @property
    def last_reject_counts(self) -> dict[str, int]:
        return dict(self._last_reject_counts)
