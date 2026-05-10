"""전략 상수. 모든 하드코딩 값은 여기에."""

from __future__ import annotations

from datetime import time

# ─── 시간 규칙 ────────────────────────────────────────────────────────────────
MARKET_OPEN              = time(9, 0)
SCAN_WINDOW_END          = time(14, 50)    # 이후에는 신규 스캔 중단
MORNING_SNAPSHOT_TIME    = time(10, 30)    # 오전 스냅샷 1회 태깅 시각
LUNCH_START              = time(11, 0)
LUNCH_END                = time(13, 0)
LATE_SESSION_START       = time(14, 0)
NO_NEW_ENTRY_TIME        = time(14, 50)    # INTRADAY/LUNCH 신규 진입 금지 (CLOSE_BET 별도)
SOFT_CLOSE_TIME          = time(15, 5)     # INTRADAY/LUNCH 조건 미달 포지션 청산
FORCE_CLOSE_TIME         = time(15, 10)    # INTRADAY/LUNCH 전량 강제 청산 — CLOSE_BET 제외
CLOSING_AUCTION_START    = time(15, 20)    # 장 마감 동시호가 시작 — 주문 NEVER 금지
NO_ORDER_AFTER           = time(15, 19, 30)  # 이 시각 이후 실전 주문 금지

# ─── 종가베팅 (CLOSE_BET) ────────────────────────────────────────────────────
CLOSE_BET_START          = time(14, 50)    # 종가베팅 진입 시작
CLOSE_BET_ENTRY_END      = time(15, 15)    # 종가베팅 마지막 진입 (동시호가 5분 전)
CLOSE_BET_START_TIME     = CLOSE_BET_START
CLOSE_BET_END_TIME       = CLOSE_BET_ENTRY_END
CLOSE_BET_SCAN_INTERVAL_SEC = 10
NEXT_OPEN_EXIT_START     = time(9,  0)     # 익일 CLOSE_BET 청산 엔진 시작
NEXT_DAY_EXIT_DEADLINE   = time(9, 30)     # 익일 CLOSE_BET 강제 청산 데드라인

CLOSE_BET_MIN_CHANGE_PCT = 0.05
CLOSE_BET_MIN_EXEC_STRENGTH_30M = 115.0
CLOSE_BET_MAX_VI_COUNT_60M = 0
CLOSE_BET_MIN_TRADING_VALUE = 100e9
CLOSE_BET_MIN_KOSDAQ_CHANGE_PCT = -0.005
MIN_EXEC_SAMPLES_30M = 3
CLOSE_BET_MAX_CHANGE_PCT = 0.20
CLOSE_BET_EXCLUDE_FRIDAY = False

AFTER_MARKET_START_TIME = time(16, 0)
AFTER_MARKET_END_TIME = time(18, 0)
AFTER_MARKET_SCAN_INTERVAL_SEC = 600
AFTER_MARKET_FILL_TIMEOUT = 600.0

# 장 초반 변동성 관리
NO_ENTRY_UNTIL           = time(9, 5)      # 09:00~09:05 신규 진입 금지 (동시호가 영향)
CONSERVATIVE_ENTRY_UNTIL = time(9, 10)     # 09:05~09:10 보수 모드 (score 추가 상향)
CONSERVATIVE_SCORE_BOOST = 10.0            # 보수 모드 시 최소 점수 상향폭

# ─── 종목 필터 ────────────────────────────────────────────────────────────────
MIN_TRADING_VALUE      = 5_000_000_000  # 거래대금 최소 50억 원
MIN_PRICE              = 1_000          # 동전주 하한
MIN_MARKET_CAP         = 50_000_000_000 # 시총 최소 500억 원
MAX_OPEN_GAP_PCT       = 0.05           # 시가 갭업 +5% 초과 종목 제외
MAX_CHANGE_NEAR_LIMIT  = 0.20           # 상한가 근접(+20% 이상) 제외
SCAN_TOP_N             = 30             # 거래대금 상위 N종목

# ─── 진입 조건 ────────────────────────────────────────────────────────────────
MIN_CHANGE_PCT      = 0.03           # 최소 등락률 +3%
MAX_CHANGE_PCT      = 0.15           # 최대 등락률 +15%
MIN_EXEC_STRENGTH   = 150.0          # 최소 체결강도
MIN_VOL_RATIO       = 3.0            # 전일 동시간 대비 최소 거래량 배율
MIN_ENTRY_SCORE     = 80.0           # 진입 최소 점수
STRONG_ENTRY_SCORE  = 90.0           # 즉시 진입 점수

# ─── 눌림 / 재돌파 ───────────────────────────────────────────────────────────
PULLBACK_MIN_PCT         = 0.010   # 유효 눌림 최소 -1.0%
PULLBACK_MAX_PCT         = 0.025   # 유효 눌림 최대 -2.5% (초과 시 제거)
PULLBACK_MAX_WAIT_SECS   = 900     # 15분 이내 눌림 미확인 시 watchlist 제거
BREAKOUT_CONFIRM_TICKS   = 2       # 고점 돌파 확인 필요 연속 틱 수 (허위 돌파 방지)
BREAKOUT_EXEC_MIN        = 130.0   # 돌파 확인 시 최소 체결강도

# ─── 대장주 얕은 눌림 진입 ───────────────────────────────────────────────────
LEADER_RANK_MAX             = 2
LEADER_MIN_SCORE            = 70.0
LEADER_SHADOW_MIN_SCORE     = 60.0
SHALLOW_PULLBACK_MIN_PCT    = 0.003   # 대장주 유효 눌림 최소 -0.3%
SHALLOW_PULLBACK_MAX_PCT    = 0.010   # 대장주 유효 눌림 최대 -1.0%
SHALLOW_ENTRY_SCORE         = 72.0
SHALLOW_ENTRY_EXEC_MIN      = 115.0
SHALLOW_ENTRY_VWAP_MIN_GAP  = -0.002  # VWAP -0.2% 이내면 회복 후보 허용
SHALLOW_ENTRY_OB_MIN        = 0.9
LEADER_HIGH_UPDATE_MIN_PCT  = 0.001   # 새 고점 0.1% 이상 갱신 시 기준 고점 갱신

# ─── Shadow 승격 기준 / continuation 진단 ───────────────────────────────────
SHADOW_MIN_SAMPLE_OPENING_MOMENTUM = 50
SHADOW_MIN_SAMPLE_LEADER_SHALLOW = 50
SHADOW_MIN_SAMPLE_VWAP_RECLAIM = 50
SHADOW_MIN_SAMPLE_SCAN_IMMEDIATE = 100
SHADOW_PROMOTION_MIN_WIN_RATE = 0.45
SHADOW_PROMOTION_MIN_MFE = 0.010
SHADOW_PROMOTION_MAX_MAE = -0.006
SHADOW_PROMOTION_MAX_FAKE_BREAKOUT = 0.55
MOMENTUM_CONTINUATION_MAX_PULLBACK_PCT = 0.004
MOMENTUM_CONTINUATION_MIN_EXEC = 108.0
MOMENTUM_CONTINUATION_MIN_VOL_RATIO = 1.5
MOMENTUM_CONTINUATION_MAX_SPREAD_PCT = 0.003

ETF_NAME_PREFIXES = (
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "HANARO", "KBSTAR",
    "ARIRANG", "KOSEF", "TIMEFOLIO", "PLUS", "TREX",
)
REIT_NAME_KEYWORDS = ("리츠", "REIT", "REITS")

# ─── 손절 / 트레일링 ─────────────────────────────────────────────────────────
ATR_STOP_MULTIPLIER    = 1.2       # Hard stop = entry - ATR × 1.2
ATR_TRAIL_MULTIPLIER   = 1.0       # Trailing stop ATR 배수
TRAIL_STOP_MAX_PCT     = 0.018     # Trailing stop 최고가 대비 -1.8% 상한
MIN_STOP_PCT           = 0.008     # 손절선 최소 거리 -0.8% (ATR 너무 작을 때 하한)

# ─── 분할 익절 ────────────────────────────────────────────────────────────────
PARTIAL_EXIT_1_PCT     = 0.020     # 1차 익절 +2.0%
PARTIAL_EXIT_1_RATIO   = 0.30      # 1차 익절 비율 30%
PARTIAL_EXIT_2_PCT     = 0.045     # 2차 익절 +4.5%
PARTIAL_EXIT_2_RATIO   = 0.30      # 2차 익절 비율 30%
FAST_EXIT_1_PCT        = 0.010     # Opening/Shallow 국장 단타 1차 익절 +1.0%
FAST_EXIT_1_RATIO      = 0.50
FAST_TIME_STOP_SECS    = 300
FAST_TIME_STOP_MIN_MFE = 0.003
FAST_TRAIL_STOP_PCT    = 0.010

# ─── 리스크 ──────────────────────────────────────────────────────────────────
DAILY_LOSS_LIMIT_PCT      = 0.030  # 일 손실 한도 -3% (실현 + 미실현 합산)
MAX_CONSECUTIVE_LOSSES    = 3      # 연속 손절 한도
MAX_SYMBOLS               = 3      # 동시 최대 보유 종목 수
MAX_POSITION_PCT          = 0.20   # 종목당 최대 계좌 비중
MAX_TOTAL_EXPOSURE_PCT    = 0.60   # 전체 포지션 최대 비중
MAX_EXPOSURE_OPENING_MOMENTUM = 0.03
MAX_EXPOSURE_SHALLOW_PULLBACK = 0.10
MAX_EXPOSURE_VWAP_RECLAIM = 0.05
MAX_EXPOSURE_DEEP_PULLBACK = 0.05
OVERNIGHT_MAX_PER_SYMBOL  = 0.05   # CLOSE_BET 종목당 최대 계좌 비중
OVERNIGHT_MAX_TOTAL       = 0.15   # CLOSE_BET 전체 최대 계좌 비중
KOSDAQ_HALT_THRESHOLD     = -0.015 # 코스닥 지수 -1.5% 이하 시 전체 차단
CIRCUIT_BREAKER_THRESHOLD = -0.08  # 코스닥 -8% → 사이드카/서킷브레이커 Kill Switch
MAX_DAILY_TRADES          = 10     # 하루 최대 진입 횟수 (과매매 방지)
MAX_TRADES_PER_SYMBOL     = 2      # 종목당 하루 최대 진입 횟수
MAX_LOSS_PER_SYMBOL_PCT   = 0.010  # 종목당 일 손실 한도 -1.0%
MAX_TRADES_PER_STRATEGY   = 4      # 전략별 하루 최대 진입 횟수
REENTRY_COOLDOWN_SECS     = 300    # 동일 종목 재진입 최소 대기 5분

# ─── 적응형 점수 임계값 (연속 손절 시 상향) ───────────────────────────────────
ADAPTIVE_SCORE_LOSS_1     = 5.0    # 연속 손절 1회 시 MIN_ENTRY_SCORE 상승폭
ADAPTIVE_SCORE_LOSS_2     = 10.0   # 연속 손절 2회 이상 시 MIN_ENTRY_SCORE 상승폭

# ─── 진입 필터 (비용 대비 수익 가능성) ───────────────────────────────────────
MAX_ENTRY_SPREAD_PCT        = 0.003   # 진입 시 허용 최대 스프레드 0.3%
MIN_ATR_COST_RATIO          = 2.0     # ATR ≥ 왕복 거래비용 × 2 (수익 가능성 보장)
EXPECTED_ENTRY_SLIPPAGE_PCT = 0.0015  # 예상 진입 슬리피지 0.15%
EXPECTED_EXIT_SLIPPAGE_PCT  = 0.0025  # 예상 청산 슬리피지 0.25%
MIN_PROFIT_COST_RATIO       = 2.0     # 슬리피지 포함 기대수익 ≥ 왕복비용 × 2

# ─── 체결강도 기반 청산 임계값 ───────────────────────────────────────────────
EXIT_EXEC_STRENGTH_MAX  = 70.0     # 체결강도 이 이하 → 청산 신호
EXIT_OB_IMBALANCE_MAX   = 0.7      # 호가잔량비 이 이하 → 청산 신호

# ─── 수수료 / 세금 ────────────────────────────────────────────────────────────
COMMISSION_RATE     = 0.00015      # 수수료 0.015% per side
TAX_RATE_KOSDAQ     = 0.0018       # 거래세 0.18% (매도, KOSDAQ)
TAX_RATE_KOSPI      = 0.0003       # 거래세 0.03% (매도, KOSPI)

# ─── ATR 파라미터 ─────────────────────────────────────────────────────────────
ATR_PERIOD          = 14
ATR_CANDLE_INTERVAL = "5"          # 5분봉
ATR_CANDLE_COUNT    = 60           # 장 시작 전 캐싱 캔들 수

# ─── VWAP ────────────────────────────────────────────────────────────────────
VWAP_WARMUP_MINUTES = 10           # 장 시작 후 이 시간 동안 VWAP 가중치 0.5배

# ─── 주문 ────────────────────────────────────────────────────────────────────
ORDER_RETRY_MAX          = 3
ORDER_RETRY_DELAY_SEC    = 0.5
ORDER_FILL_TIMEOUT_SEC   = 10.0
MAX_SLIPPAGE_PCT         = 0.003   # 허용 슬리피지 0.3%

# ─── VI (Volatility Interruption) ────────────────────────────────────────────
VI_COOLDOWN_SECS             = 180   # VI 해제 후 3분 대기

# ─── 장애 내성 / 안정성 ─────────────────────────────────────────────────────
MAX_RISK_STORE_ERRORS        = 3     # Redis save_risk 연속 실패 허용 횟수 (초과 시 kill_switch)
MAX_POS_STORE_ERRORS         = 2     # Redis save_position 연속 실패 허용 횟수
STOPPING_WS_BACKOFF_CAP      = 5.0   # STOPPING 중 WS 재연결 최대 backoff 초
WS_RESUB_COOLDOWN_SECS       = 30.0  # WS 재구독 쿨다운 (과도한 reconnect 방지)
CB_RESUME_POLL_SECS          = 30.0  # 서킷브레이커 해제 감지 폴링 주기
SNAPSHOT_VERSION             = 2     # StateStore 포지션 스냅샷 버전

# ─── Market Regime ────────────────────────────────────────────────────────────
REGIME_CONFIRM_SECS              = 300    # 레짐 전환 확인 시간 (5분) — 급격한 전환 방지
REGIME_SCORE_AGGRESSIVE          = 70     # 이 이상 → KOSDAQ_AGGRESSIVE
REGIME_SCORE_NORMAL              = 40     # 이 이상 → KOSDAQ_NORMAL
RESTART_REGIME_CONFIRM_SECS      = 60     # 장중 재시작/warmup 중 soft 전환 확인 시간
STRONG_REGIME_CONFIRM_SECS       = 30     # 후보 수/점수가 충분히 강할 때 확인 시간
REGIME_CANDIDATE_MIN_UPDATES     = 3      # false positive 방지용 최소 유효 업데이트 수
REGIME_CANDIDATE_TTL_SEC         = 120    # 마지막 유효 후보 레짐 유지 시간
DATA_STALE_SEC                   = 120
API_STALL_SEC                    = 180
SCAN_API_TIMEOUT_SEC             = 2.0
INDEX_API_TIMEOUT_SEC            = 1.0
BALANCE_API_TIMEOUT_SEC          = 2.0
FAKE_BREAKOUT_NO_TRADE_THRESHOLD = 0.70   # 가짜 돌파 비율 70% 초과 → 즉시 NO_TRADE
FAKE_BREAKOUT_TIGHTEN_THRESHOLD  = 0.55   # 55% 초과 → 진입 기준 강화 신호
VI_DENSITY_NO_TRADE_COUNT        = 10     # 30분 내 VI 10회 이상 → NO_TRADE
VI_DENSITY_WINDOW_SECS           = 1800   # VI 밀도 측정 윈도우 30분

# ─── 점수 가중치 (합계 100) ───────────────────────────────────────────────────
W_EXEC_STRENGTH     = 35   # 핵심 수급 지표 (30→35; OB 의존도 낮춰 실전 안정성 향상)
W_VOL_RATIO         = 20
W_VWAP_GAP          = 20
W_OB_IMBALANCE      = 10   # 호가잔량비는 보조지표 (15→10; 얕은 호가 조작 가능성 반영)
W_MARKET_STRENGTH   = 10
W_VOLATILITY        = 5
