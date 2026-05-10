"""실시간 로그 대시보드 서버."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

LOG_FILE = Path(__file__).parent / "paper_trading.log"
REPORT_DIR = Path(__file__).parent / "data" / "strategy_reports"
PROMOTION_STATE = Path(__file__).parent / "data" / "strategy_promotion" / "current.json"
DIAGNOSTICS_DIR = Path(__file__).parent / "data" / "strategy_diagnostics"
MAX_HISTORY = 500   # 최초 로드 시 보여줄 최근 줄 수

app = FastAPI()

# ------------------------------------------------------------------
# HTML
# ------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vibe Trading — 실시간 로그</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --blue: #58a6ff; --purple: #bc8cff; --orange: #ffa657;
    --cyan: #39d353;
  }
  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }

  /* Header */
  header {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 14px 20px; display: flex; align-items: center; gap: 16px;
    position: sticky; top: 0; z-index: 10;
  }
  header h1 { font-size: 15px; font-weight: 600; color: var(--text); }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--green);
    box-shadow: 0 0 6px var(--green);
    animation: pulse 2s infinite;
  }
  .status-dot.offline { background: var(--red); box-shadow: 0 0 6px var(--red); animation: none; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

  /* Stats bar */
  .stats {
    display: flex; gap: 0; background: var(--surface);
    border-bottom: 1px solid var(--border); padding: 0 20px;
  }
  .stat {
    padding: 10px 20px 10px 0; margin-right: 20px;
    border-right: 1px solid var(--border);
  }
  .stat:last-child { border-right: none; }
  .stat-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
  .stat-value { color: var(--text); font-size: 16px; font-weight: 600; margin-top: 2px; }
  .stat-value.green { color: var(--green); }
  .stat-value.yellow { color: var(--yellow); }
  .stat-value.red { color: var(--red); }
  .stat-value.blue { color: var(--blue); }
  .stat-sub { color: var(--muted); font-size: 11px; margin-top: 3px; white-space: nowrap; }

  /* Strategy timeline */
  .strategy-panel {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 10px 20px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }
  .strategy-cell {
    border: 1px solid var(--border); border-radius: 6px; padding: 9px 10px;
    min-width: 0; background: rgba(255,255,255,0.015);
  }
  .strategy-label { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
  .strategy-value { color: var(--text); font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .strategy-detail { color: var(--muted); font-size: 11px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .strategy-active { color: var(--green); }
  .strategy-blocked { color: var(--yellow); }
  .strategy-inactive { color: var(--muted); }

  .metrics-panel {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 10px 20px; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 10px;
  }
  .metric-cell {
    border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px;
    min-width: 0; background: rgba(255,255,255,0.015);
  }
  .metric-label { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
  .metric-value { color: var(--text); font-size: 13px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .metric-detail { color: var(--muted); font-size: 11px; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* Filter bar */
  .filters {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 8px 20px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  }
  .filter-btn {
    padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border);
    background: transparent; color: var(--muted); cursor: pointer; font-size: 12px;
    font-family: inherit; transition: all 0.15s;
  }
  .filter-btn:hover { border-color: var(--blue); color: var(--blue); }
  .filter-btn.active { background: var(--blue); border-color: var(--blue); color: #000; font-weight: 600; }
  .filter-btn.active-green { background: var(--green); border-color: var(--green); color: #000; font-weight: 600; }
  .filter-btn.active-yellow { background: var(--yellow); border-color: var(--yellow); color: #000; font-weight: 600; }
  .filter-btn.active-red { background: var(--red); border-color: var(--red); color: #fff; font-weight: 600; }
  .search {
    margin-left: auto; padding: 4px 10px; border-radius: 4px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-size: 12px; font-family: inherit; width: 200px;
  }
  .search:focus { outline: none; border-color: var(--blue); }
  .scroll-btn {
    padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border);
    background: var(--bg); color: var(--muted); cursor: pointer; font-size: 12px;
    font-family: inherit;
  }
  .scroll-btn.active { border-color: var(--green); color: var(--green); }

  /* Log area */
  #log-container {
    height: calc(100vh - 224px); overflow-y: auto; padding: 8px 0;
  }
  .log-line {
    display: flex; padding: 2px 20px; gap: 12px; line-height: 1.5;
    border-left: 3px solid transparent; transition: background 0.1s;
  }
  .log-line:hover { background: rgba(255,255,255,0.03); }
  .log-line.new { animation: flash 0.4s ease-out; }
  @keyframes flash { from { background: rgba(88,166,255,0.12); } to { background: transparent; } }

  .log-line.level-CRITICAL { border-left-color: var(--red); }
  .log-line.level-ERROR    { border-left-color: var(--red); }
  .log-line.level-WARNING  { border-left-color: var(--yellow); }
  .log-line.cat-ops { border-left-color: var(--muted); opacity: 0.86; }

  .ts  { color: var(--muted); white-space: nowrap; font-size: 12px; min-width: 90px; }
  .lvl { white-space: nowrap; min-width: 56px; font-weight: 600; font-size: 11px; }
  .msg { flex: 1; word-break: break-all; }

  .lvl-INFO     { color: var(--blue); }
  .lvl-WARNING  { color: var(--yellow); }
  .lvl-ERROR    { color: var(--red); }
  .lvl-CRITICAL { color: var(--red); text-shadow: 0 0 8px var(--red); }
  .lvl-DEBUG    { color: var(--muted); }

  /* Keyword highlights */
  .kw-regime   { color: var(--purple); font-weight: 600; }
  .kw-strategy { color: var(--purple); font-weight: 600; }
  .kw-risk     { color: var(--orange); }
  .kw-buy      { color: var(--green); font-weight: 600; }
  .kw-sell     { color: var(--red); font-weight: 600; }
  .kw-capital  { color: var(--cyan); font-weight: 600; }
  .kw-account  { color: var(--cyan); font-weight: 600; }
  .kw-ops      { color: var(--muted); font-weight: 600; }
  .kw-error    { color: var(--red); }
  .kw-ok       { color: var(--green); }
  .kw-ws       { color: #79c0ff; }

  /* Candidate popup */
  .candidate-popup {
    position: fixed; top: 128px; right: 24px; width: 280px; max-height: 420px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
    box-shadow: 0 10px 32px rgba(0,0,0,0.35); z-index: 30; overflow: hidden;
  }
  .candidate-popup.hidden { display: none; }
  .candidate-head {
    padding: 10px 12px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--border); cursor: move; user-select: none;
  }
  .candidate-title { font-size: 12px; font-weight: 700; color: var(--blue); }
  .candidate-meta { color: var(--muted); font-size: 11px; }
  .candidate-close {
    border: 1px solid var(--border); background: var(--bg); color: var(--muted);
    width: 22px; height: 22px; border-radius: 4px; cursor: pointer;
  }
  .candidate-list { padding: 8px; max-height: 350px; overflow-y: auto; }
  .candidate-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 7px 8px; border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .candidate-item:last-child { border-bottom: none; }
  .candidate-symbol { font-size: 13px; color: var(--text); font-weight: 700; }
  .candidate-tag { font-size: 10px; color: var(--green); border: 1px solid rgba(63,185,80,0.5); padding: 2px 5px; border-radius: 4px; }
  .candidate-empty { color: var(--muted); padding: 12px; font-size: 12px; line-height: 1.5; }

  .hidden { display: none !important; }
</style>
</head>
<body>
<header>
  <div class="status-dot" id="dot"></div>
  <h1>Vibe Trading &nbsp;/&nbsp; 모의투자 실시간 로그</h1>
  <span id="hdr-regime" style="margin-left:auto; font-size:12px; color:var(--muted);">레짐 로딩 중…</span>
</header>

<div class="stats">
  <div class="stat">
    <div class="stat-label">자금</div>
    <div class="stat-value blue" id="st-capital">—</div>
  </div>
  <div class="stat">
    <div class="stat-label">레짐</div>
    <div class="stat-value" id="st-regime">—</div>
  </div>
  <div class="stat">
    <div class="stat-label">스코어</div>
    <div class="stat-value" id="st-score">—</div>
  </div>
  <div class="stat">
    <div class="stat-label">손익 (PnL)</div>
    <div class="stat-value" id="st-pnl">—</div>
  </div>
  <div class="stat">
    <div class="stat-label">매매 횟수</div>
    <div class="stat-value" id="st-trades">—</div>
  </div>
  <div class="stat">
    <div class="stat-label">후보 종목</div>
    <div class="stat-value" id="st-candidates">—</div>
  </div>
  <div class="stat">
    <div class="stat-label">진입 미달</div>
    <div class="stat-value yellow" id="st-entry-gap">—</div>
    <div class="stat-sub" id="st-entry-gap-sub">신호 대기</div>
  </div>
  <div class="stat">
    <div class="stat-label">전략</div>
    <div class="stat-value" id="st-strategy">—</div>
    <div class="stat-sub" id="st-strategy-sub">대기 중</div>
  </div>
</div>

<div class="strategy-panel">
  <div class="strategy-cell">
    <div class="strategy-label">지금 사용중인 전략</div>
    <div class="strategy-value" id="strategy-current">—</div>
    <div class="strategy-detail" id="strategy-current-detail">상태 로그 대기</div>
  </div>
  <div class="strategy-cell">
    <div class="strategy-label">남은 시간</div>
    <div class="strategy-value" id="strategy-remaining">—</div>
    <div class="strategy-detail" id="strategy-end">종료 시각 —</div>
  </div>
  <div class="strategy-cell">
    <div class="strategy-label">앞으로 적용할 전략</div>
    <div class="strategy-value" id="strategy-next">—</div>
    <div class="strategy-detail" id="strategy-next-start">시작 시각 —</div>
  </div>
</div>

<div class="metrics-panel">
  <div class="metric-cell">
    <div class="metric-label">후보 → 전략 후보</div>
    <div class="metric-value" id="mx-funnel">—</div>
    <div class="metric-detail" id="mx-funnel-detail">report 대기</div>
  </div>
  <div class="metric-cell">
    <div class="metric-label">신호 / Shadow / 주문 / 체결</div>
    <div class="metric-value" id="mx-conversion">—</div>
    <div class="metric-detail" id="mx-conversion-detail">conversion 대기</div>
  </div>
  <div class="metric-cell">
    <div class="metric-label">Top Reject / Freshness</div>
    <div class="metric-value" id="mx-reject">—</div>
    <div class="metric-detail" id="mx-freshness">stale — · VWAP —</div>
  </div>
  <div class="metric-cell">
    <div class="metric-label">Promotion State</div>
    <div class="metric-value" id="mx-promotion">—</div>
    <div class="metric-detail" id="mx-expectancy">expectancy —</div>
  </div>
  <div class="metric-cell">
    <div class="metric-label">Runtime Regime</div>
    <div class="metric-value" id="mx-runtime-regime">—</div>
    <div class="metric-detail" id="mx-runtime-detail">score —</div>
  </div>
  <div class="metric-cell">
    <div class="metric-label">Execution Gate</div>
    <div class="metric-value" id="mx-execution">—</div>
    <div class="metric-detail" id="mx-permission">permission —</div>
  </div>
</div>

<div class="filters">
  <button class="filter-btn active" id="f-all"    onclick="setFilter('all')">전체</button>
  <button class="filter-btn" id="f-regime"  onclick="setFilter('regime')">레짐</button>
  <button class="filter-btn" id="f-strategy" onclick="setFilter('strategy')">전략</button>
  <button class="filter-btn" id="f-risk"    onclick="setFilter('risk')">리스크</button>
  <button class="filter-btn" id="f-scan"    onclick="setFilter('scan')">스캔</button>
  <button class="filter-btn" id="f-trade"   onclick="setFilter('trade')">주문/체결</button>
  <button class="filter-btn" id="f-ws"      onclick="setFilter('ws')">WebSocket</button>
  <button class="filter-btn" id="f-ops"     onclick="setFilter('ops')">운영</button>
  <button class="filter-btn" id="f-warn"    onclick="setFilter('warn')">경고/에러</button>
  <input  class="search" id="search" placeholder="검색…" oninput="applyFilter()">
  <button class="scroll-btn active" id="auto-scroll-btn" onclick="toggleAutoScroll()">↓ 자동스크롤 ON</button>
</div>

<div id="log-container"></div>

<div id="candidate-popup" class="candidate-popup hidden">
  <div id="candidate-head" class="candidate-head">
    <div>
      <div class="candidate-title">후보 종목</div>
      <div class="candidate-meta" id="candidate-meta">0개</div>
    </div>
    <button class="candidate-close" onclick="hideCandidatePopup()">×</button>
  </div>
  <div class="candidate-list" id="candidate-list">
    <div class="candidate-empty">후보 종목 로그를 기다리는 중입니다.</div>
  </div>
</div>

<script>
const MAX_LINES = 2000;
let lines = [];
let currentFilter = 'all';
let autoScroll = true;
let searchTerm = '';
let candidateSymbols = [];
let candidateCount = 0;
let candidatePopupDismissed = false;

const container = document.getElementById('log-container');
const candidatePopup = document.getElementById('candidate-popup');
const candidateList = document.getElementById('candidate-list');
const candidateMeta = document.getElementById('candidate-meta');

// ── 상태 파싱 ────────────────────────────────────────────────────
function updateStats(text) {
  // Capital
  const cap = text.match(/Capital:\\s*([\\d,]+)/);
  if (cap) document.getElementById('st-capital').textContent =
    parseInt(cap[1].replace(/,/g,'')).toLocaleString('ko-KR') + '원';

  const account = text.match(/\\[Account\\]\\s+deposit=([\\d.\\-]+)\\s+total_eval=([\\d.\\-]+).*pnl=([\\d.\\-]+)\\(([\\d.\\-]+)%\\)\\s+holdings=(\\d+)/);
  if (account) {
    const deposit = parseFloat(account[1]);
    const totalEval = parseFloat(account[2]);
    const pnl = parseFloat(account[3]);
    const pnlPct = parseFloat(account[4]);
    const base = totalEval > 0 ? totalEval : deposit;
    const el = document.getElementById('st-capital');
    el.textContent = base.toLocaleString('ko-KR') + '원';
    el.title = `예수금 ${deposit.toLocaleString('ko-KR')}원 / 평가손익 ${pnl.toLocaleString('ko-KR')}원 (${pnlPct.toFixed(2)}%) / 보유 ${account[5]}종목`;
    el.className = 'stat-value ' + (pnl > 0 ? 'green' : pnl < 0 ? 'red' : 'blue');
  }

  const strategy = text.match(/\\[StrategySchedule\\]\\s+current=(\\S+)\\s+label=(\\S+)\\s+active=(true|false)\\s+reason=(\\S+)(?:\\s+block_reason=(\\S+))?\\s+current_end=(\\S+)\\s+remaining_sec=(\\d+)\\s+next=(\\S+)\\s+next_label=(\\S+)\\s+next_start=(\\S+)(.*)$/);
  if (strategy) {
    const tail = strategy[11] || '';
    const diag = Object.fromEntries([...tail.matchAll(/(hard_no_trade|current_regime|candidate_regime|candidate_score|candidate_age_sec|confirm_required_sec|confirm_remaining_sec|last_valid_scan_age_sec|api_stall|signal_state|watchlist_count|subscribed_count|position_count|order_count|top_block)=([^\\s]+)/g)].map(m => [m[1], m[2]]));
    updateStrategyPanel({
      current: strategy[1],
      label: prettyStrategyLabel(strategy[2]),
      active: strategy[3] === 'true',
      reason: strategy[4],
      blockReason: strategy[5] || strategy[4],
      currentEnd: strategy[6],
      remainingSec: parseInt(strategy[7], 10),
      next: strategy[8],
      nextLabel: prettyStrategyLabel(strategy[9]),
      nextStart: strategy[10],
      diag,
    });
    if (strategy[1] !== 'INTRADAY_SCALP') {
      clearCandidatePopup(`${prettyStrategyLabel(strategy[2])} 구간입니다. 장중 스캘핑 후보는 초기화했습니다.`);
    }
  }

  const noEntry = text.match(/\\[(?:NoEntryDiagnosis|SignalSummary)\\].*best_score=([\\d.\\-]+).*avg_score_gap=([\\d.\\-]+).*avg_exec_strength_gap=([\\d.\\-]+).*avg_vol_ratio_gap=([\\d.\\-]+).*avg_pullback_gap_pct=([\\d.\\-]+).*top_missing_metric=(\\S+).*near_entry=(\\d+)/);
  if (noEntry) {
    updateEntryGapPanel({
      bestScore: parseFloat(noEntry[1]),
      scoreGap: parseFloat(noEntry[2]),
      execGap: parseFloat(noEntry[3]),
      volGap: parseFloat(noEntry[4]),
      pullbackGap: parseFloat(noEntry[5]),
      topMissing: noEntry[6],
      nearEntry: parseInt(noEntry[7], 10),
    });
  }

  // Regime
  const reg = text.match(/\\[Regime\\]\\s+(\\S+)\\s+score=([\\d.]+).*\\|?\\s*(?:spread=|$)/);
  const regScore = text.match(/score=([\\d.]+)/);
  if (reg || regScore) {
    if (reg) {
      const regime = reg[1];
      const el = document.getElementById('st-regime');
      const hdr = document.getElementById('hdr-regime');
      el.textContent = regime;
      hdr.textContent = '레짐: ' + regime;
      el.className = 'stat-value' +
        (regime.includes('aggressive') ? ' green' :
         regime.includes('normal') ? ' blue' :
         regime.includes('defensive') ? ' yellow' : ' red');
    }
    if (regScore) document.getElementById('st-score').textContent = regScore[1];
  }

  // Candidates from scan
  const scan = text.match(/MarketScanner:\\s*(\\d+)\\s*\\/\\s*(\\d+)/);
  if (scan) {
    candidateCount = parseInt(scan[1], 10);
    document.getElementById('st-candidates').textContent = scan[1] + ' / ' + scan[2];
    if (candidateCount <= 0) candidateSymbols = [];
    renderCandidatePopup();
  }

  const closeBetScan = text.match(/CLOSE_BET_SCAN\\s+raw=(\\d+)\\s+passed=(\\d+)/);
  if (closeBetScan) {
    candidateCount = parseInt(closeBetScan[2], 10);
    candidateSymbols = [];
    document.getElementById('st-candidates').textContent = closeBetScan[2] + ' / close';
    renderCandidatePopup();
  }

  if (/\\[CLOSE_BET_NO_CANDIDATE\\]/.test(text)) {
    clearCandidatePopup('종가베팅 후보가 없습니다. 스캔은 실행됐지만 조건 미충족입니다.');
  }

  const symbols = extractCandidateSymbols(text);
  if (symbols.length) {
    candidateSymbols = symbols;
    renderCandidatePopup();
  }

  // Risk
  const risk = text.match(/pnl=([\\d.\\-]+)\\(([\\d.\\-]+)%\\)\\s+trades=(\\d+)/);
  if (risk) {
    const pnl = parseFloat(risk[1]);
    const pnlPct = parseFloat(risk[2]);
    const el = document.getElementById('st-pnl');
    el.textContent = pnl.toLocaleString('ko-KR') + '원 (' + (pnlPct > 0 ? '+' : '') + pnlPct.toFixed(2) + '%)';
    el.className = 'stat-value' + (pnl > 0 ? ' green' : pnl < 0 ? ' red' : '');
    document.getElementById('st-trades').textContent = risk[3];
  }
}

function prettyStrategyLabel(value) {
  return value.replace(/_/g, ' ');
}

function formatRemaining(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}시간 ${m}분`;
  if (m > 0) return `${m}분 ${s}초`;
  return `${s}초`;
}

function updateStrategyPanel(s) {
  const statusText = s.active ? `활성 · ${prettyStrategyLabel(s.diag.signal_state || 'ok')}` : `대기/차단: ${prettyStrategyLabel(s.blockReason || s.reason)}`;
  const statusClass = s.active ? 'strategy-active' :
    (s.reason === 'market_closed' || s.reason === 'pre_market' ? 'strategy-inactive' : 'strategy-blocked');

  const stat = document.getElementById('st-strategy');
  stat.textContent = s.label;
  stat.className = 'stat-value ' + (s.active ? 'green' : statusClass === 'strategy-blocked' ? 'yellow' : '');
  const diagText = s.diag && s.diag.candidate_regime && s.diag.candidate_regime !== '-'
    ? ` · 후보 ${prettyStrategyLabel(s.diag.candidate_regime)} ${s.diag.candidate_age_sec || 0}/${s.diag.confirm_required_sec || 0}s`
    : '';
  document.getElementById('st-strategy-sub').textContent = `${statusText} · ${formatRemaining(s.remainingSec)}${diagText}`;

  const current = document.getElementById('strategy-current');
  current.textContent = s.label;
  current.className = 'strategy-value ' + statusClass;
  document.getElementById('strategy-current-detail').textContent = `${s.current} · ${statusText} · 레짐 ${s.diag.current_regime || '—'} · top ${s.diag.top_block || '—'}`;
  document.getElementById('strategy-remaining').textContent = formatRemaining(s.remainingSec);
  document.getElementById('strategy-end').textContent = `종료 시각 ${s.currentEnd}`;
  document.getElementById('strategy-next').textContent = s.nextLabel;
  document.getElementById('strategy-next-start').textContent = `${s.next} · 시작 ${s.nextStart}`;
}

function updateEntryGapPanel(g) {
  const el = document.getElementById('st-entry-gap');
  const sub = document.getElementById('st-entry-gap-sub');
  const close = g.nearEntry > 0 || g.scoreGap <= 5;
  el.textContent = `최고 ${g.bestScore.toFixed(1)} / 평균 -${g.scoreGap.toFixed(1)}점`;
  el.className = 'stat-value ' + (close ? 'green' : 'yellow');
  sub.textContent = `체결강도 -${g.execGap.toFixed(1)} · 거래량 -${g.volGap.toFixed(2)}x · 눌림 -${g.pullbackGap.toFixed(2)}% · ${prettyStrategyLabel(g.topMissing)} · 근접 ${g.nearEntry}`;
}

function clearCandidatePopup(message) {
  candidateCount = 0;
  candidateSymbols = [];
  document.getElementById('st-candidates').textContent = '0';
  candidateMeta.textContent = '0개';
  candidateList.innerHTML = `<div class="candidate-empty">${escHtml(message || '후보 종목이 없습니다.')}</div>`;
  candidatePopup.classList.add('hidden');
}

function extractCandidateSymbols(text) {
  const detail = text.match(/\\[ScanCandidates\\]\\s+count=(\\d+)\\s+candidates=([^\\n]+)/);
  if (detail) {
    candidateCount = parseInt(detail[1], 10);
    document.getElementById('st-candidates').textContent = detail[1] + ' / scan';
    return detail[2]
      .split(',')
      .map(raw => {
        const parts = raw.trim().split(':');
        return {
          symbol: (parts[0] || '').trim(),
          name: (parts[1] || '').trim(),
          change: (parts[2] || '').trim(),
        };
      })
      .filter(c => c.symbol);
  }

  const m = text.match(/symbols=\\[([^\\]]+)\\]/);
  if (!m) return [];
  return [...new Set(
    m[1]
      .split(',')
      .map(s => s.replace(/['"\\s]/g, ''))
      .filter(Boolean)
  )].map(symbol => ({symbol, name: '', change: ''}));
}

function renderCandidatePopup() {
  candidateMeta.textContent = `${candidateSymbols.length || candidateCount}개`;
  if (candidateCount <= 0 && candidateSymbols.length === 0) {
    candidatePopup.classList.add('hidden');
    return;
  }
  if (!candidatePopupDismissed) candidatePopup.classList.remove('hidden');
  if (!candidateSymbols.length) {
    candidateList.innerHTML = '<div class="candidate-empty">후보 수는 감지됐지만 아직 구독 종목 리스트 로그가 없습니다.</div>';
    return;
  }
  candidateList.innerHTML = candidateSymbols.map(c =>
    `<div class="candidate-item"><span><span class="candidate-symbol">${escHtml(c.name || c.symbol)}</span>${c.change ? ` <span class="candidate-meta">${escHtml(c.change)}</span>` : ''}</span><span class="candidate-tag">WATCH</span></div>`
  ).join('');
}

function hideCandidatePopup() {
  candidatePopupDismissed = true;
  candidatePopup.classList.add('hidden');
}

function initCandidateDrag() {
  const head = document.getElementById('candidate-head');
  let dragging = false;
  let dx = 0;
  let dy = 0;
  head.addEventListener('mousedown', e => {
    dragging = true;
    const rect = candidatePopup.getBoundingClientRect();
    dx = e.clientX - rect.left;
    dy = e.clientY - rect.top;
    candidatePopup.style.right = 'auto';
    document.body.style.userSelect = 'none';
  });
  window.addEventListener('mousemove', e => {
    if (!dragging) return;
    const maxX = window.innerWidth - candidatePopup.offsetWidth;
    const maxY = window.innerHeight - candidatePopup.offsetHeight;
    candidatePopup.style.left = Math.max(0, Math.min(maxX, e.clientX - dx)) + 'px';
    candidatePopup.style.top = Math.max(0, Math.min(maxY, e.clientY - dy)) + 'px';
  });
  window.addEventListener('mouseup', () => {
    dragging = false;
    document.body.style.userSelect = '';
  });
}

// ── 로그 라인 분류 ──────────────────────────────────────────────
function classify(line) {
  if (isOperationalStop(line)) return 'ops';
  if (/\\[StrategySchedule\\]|\\[SignalSummary\\]|\\[NoEntryDiagnosis\\]|\\[SignalState\\]/.test(line)) return 'strategy';
  if (/\\[Regime\\]/.test(line)) return 'regime';
  if (/\\[Risk\\]/.test(line)) return 'risk';
  if (/\\[Account\\]|Capital:/.test(line)) return 'risk';
  if (/MarketScanner/.test(line)) return 'scan';
  if (/H0STCNI9|H0STCNT0|WS |websocket|WebSocket|subscribe|SUBSCRIBE SUCCESS|KISTickSubscriber/.test(line)) return 'ws';
  if (/\\b(Order submitted|ENTRY:|EXIT:|CLOSE_BET_ENTRY:|AFTER_MARKET|Fill timeout|Liquidat(?:e|ing)|partial=|filled=|order_no=|ODNO)\\b/.test(line)) return 'trade';
  if (/WARNING|ERROR|CRITICAL/.test(line)) return 'warn';
  return 'other';
}

function isOperationalStop(line) {
  return /reason=signal/.test(line) ||
    /\\[STOPPING\\]\\s+(Monitor started|No positions to liquidate|All positions cleared)/.test(line) ||
    /\\[STOPPING→TERMINATED\\]/.test(line) ||
    /봇 종료 완료|ScalpingBot teardown complete|모의투자 봇 시작|봇 실행 중/.test(line);
}

function matchesFilter(cat, level) {
  if (currentFilter === 'all') return true;
  if (currentFilter === 'warn') return cat !== 'ops' && (level === 'WARNING' || level === 'ERROR' || level === 'CRITICAL');
  return cat === currentFilter;
}

function matchesSearch(text) {
  if (!searchTerm) return true;
  return text.toLowerCase().includes(searchTerm.toLowerCase());
}

// ── 하이라이트 ──────────────────────────────────────────────────
function highlight(msg) {
  return msg
    .replace(/\\[StrategySchedule\\]/g, '<span class="kw-strategy">[StrategySchedule]</span>')
    .replace(/\\[(SignalSummary|NoEntryDiagnosis|SignalState)\\]/g, '<span class="kw-strategy">[$1]</span>')
    .replace(/\\[Regime\\]/g, '<span class="kw-regime">[Regime]</span>')
    .replace(/\\[Risk\\]/g,   '<span class="kw-risk">[Risk]</span>')
    .replace(/\\b(buy|매수|BUY)\\b/gi, '<span class="kw-buy">$1</span>')
    .replace(/\\b(sell|매도|SELL)\\b/gi,'<span class="kw-sell">$1</span>')
    .replace(/(Capital:\\s*[\\d,]+)/g, '<span class="kw-capital">$1</span>')
    .replace(/(\\[Account\\])/g, '<span class="kw-account">$1</span>')
    .replace(/(SUBSCRIBE SUCCESS|WS subscribe ok)/g, '<span class="kw-ws">$1</span>')
    .replace(/(kosdaq_normal|kosdaq_aggressive)/g, '<span class="kw-ok">$1</span>')
    .replace(/(ERROR|error|failed|실패)/g, '<span class="kw-error">$1</span>')
    .replace(/(reason=signal|\\[STOPPING→TERMINATED\\]|\\[running→STOPPING\\]|\\[STOPPING\\]|STOPPING|TERMINATED)/g, '<span class="kw-ops">$1</span>')
    .replace(/(no_trade|NO_TRADE)/g, '<span class="kw-error">$1</span>');
}

// ── DOM 라인 생성 ────────────────────────────────────────────────
function buildEl(parsed, isNew) {
  const {ts, level, msg, cat} = parsed;
  const el = document.createElement('div');
  el.className = 'log-line level-' + level + ' cat-' + cat + (isNew ? ' new' : '');

  const hidden = !matchesFilter(cat, level) || !matchesSearch(ts + ' ' + msg);
  if (hidden) el.classList.add('hidden');
  el.dataset.cat = cat;
  el.dataset.level = level;
  el.dataset.text = (ts + ' ' + msg).toLowerCase();

  el.innerHTML =
    '<span class="ts">' + ts.slice(11, 23) + '</span>' +
    '<span class="lvl lvl-' + level + '">' + level + '</span>' +
    '<span class="msg">' + highlight(escHtml(msg)) + '</span>';
  return el;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── 파싱 ────────────────────────────────────────────────────────
// 2026-05-07 10:46:43,786 INFO     src.xxx  message
const RE = /^(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2},\\d+)\\s+(\\w+)\\s+\\S+\\s+(.*)$/;

function parseLine(raw) {
  const m = raw.match(RE);
  if (!m) return {ts: '', level: 'DEBUG', msg: raw, cat: 'other'};
  return {ts: m[1], level: m[2], msg: m[3], cat: classify(raw)};
}

// ── 라인 추가 ────────────────────────────────────────────────────
function addLine(raw, isNew) {
  if (!raw.trim()) return;
  const parsed = parseLine(raw);
  if (isNew) updateStats(raw);

  lines.push({raw, parsed});
  if (lines.length > MAX_LINES) {
    lines.shift();
    if (container.lastChild) container.removeChild(container.lastChild);
  }

  const el = buildEl(parsed, isNew);
  container.prepend(el);

  if (autoScroll && !el.classList.contains('hidden')) {
    container.scrollTop = 0;
  }
}

// ── 필터 / 검색 ─────────────────────────────────────────────────
function setFilter(f) {
  currentFilter = f;
  ['all','regime','strategy','risk','scan','trade','ws','ops','warn'].forEach(id => {
    const btn = document.getElementById('f-' + id);
    if (!btn) return;
    btn.className = 'filter-btn' + (id === f ? ' active' : '');
  });
  applyFilter();
}

function applyFilter() {
  searchTerm = document.getElementById('search').value;
  container.querySelectorAll('.log-line').forEach((el, i) => {
    const {cat, level, text} = el.dataset;
    const show = matchesFilter(cat, level) && matchesSearch(text);
    el.classList.toggle('hidden', !show);
  });
  if (autoScroll) {
    container.scrollTop = 0;
  }
}

// ── 자동스크롤 토글 ─────────────────────────────────────────────
function toggleAutoScroll() {
  autoScroll = !autoScroll;
  const btn = document.getElementById('auto-scroll-btn');
  btn.textContent = autoScroll ? '↓ 자동스크롤 ON' : '자동스크롤 OFF';
  btn.className = 'scroll-btn' + (autoScroll ? ' active' : '');
}

container.addEventListener('wheel', () => {
  if (autoScroll) {
    autoScroll = false;
    const btn = document.getElementById('auto-scroll-btn');
    btn.textContent = '자동스크롤 OFF';
    btn.className = 'scroll-btn';
  }
});

// ── SSE 연결 ─────────────────────────────────────────────────────
function connect() {
  const es = new EventSource('/stream');
  const dot = document.getElementById('dot');

  es.addEventListener('history', e => {
    const history = JSON.parse(e.data);
    history.forEach(l => addLine(l, false));
    if (autoScroll) {
      container.scrollTop = 0;
    }
  });

  es.addEventListener('line', e => {
    addLine(JSON.parse(e.data), true);
  });

  es.onopen = () => { dot.className = 'status-dot'; };
  es.onerror = () => {
    dot.className = 'status-dot offline';
    es.close();
    setTimeout(connect, 3000);
  };
}

function sumObjectValues(obj) {
  return Object.values(obj || {}).reduce((a, b) => a + Number(b || 0), 0);
}

function firstEntry(obj) {
  const entries = Object.entries(obj || {});
  return entries.length ? entries[0] : ['—', 0];
}

async function refreshStrategyMetrics() {
  try {
    const res = await fetch('/strategy-metrics', { cache: 'no-store' });
    if (!res.ok) return;
    const payload = await res.json();
    const m = payload.metrics || {};
    const report = payload.report || {};
    const promotion = payload.promotion || {};
    const latest = payload.latest || {};
    const funnel = report.conversion_funnel || {};
    const strategyCandidates = m.strategy_candidates || {};
    const signals = m.signals || {};
    const shadowEntries = funnel.shadow_entry_count_by_strategy || {};
    const raw = Number(m.raw_candidates || 0);
    const strategyCount = sumObjectValues(strategyCandidates);
    const signalCount = sumObjectValues(signals);
    const shadowCount = sumObjectValues(shadowEntries);
    const orders = Number(m.orders || 0);
    const fills = Number(m.fills || 0);
    const [rejectReason, rejectCount] = firstEntry(m.top_reject_reasons || {});
    const fresh = m.feature_freshness || {};
    const states = promotion.states || {};
    const stateText = Object.entries(states).slice(0, 3).map(([k, v]) => `${k}:${v}`).join(' · ') || 'shadow_only';
    const exp = m.shadow_expectancy || {};
    const expText = Object.entries(exp).slice(0, 2).map(([k, v]) => `${k}:${Number(v || 0).toFixed(3)}`).join(' · ') || '—';
    const runtime = latest.regime_snapshot || {};
    const execution = latest.execution_quality || {};
    const permission = latest.runtime_permission || {};

    document.getElementById('mx-funnel').textContent = `${raw} → ${strategyCount}`;
    document.getElementById('mx-funnel-detail').textContent = `전략 후보 ${Object.keys(strategyCandidates).length}종`;
    document.getElementById('mx-conversion').textContent = `${signalCount} / ${shadowCount} / ${orders} / ${fills}`;
    document.getElementById('mx-conversion-detail').textContent = 'signal / shadow / order / fill';
    document.getElementById('mx-reject').textContent = `${rejectReason} ${rejectCount || ''}`;
    document.getElementById('mx-freshness').textContent = `stale ${(Number(fresh.stale_tick_ratio || 0) * 100).toFixed(1)}% · VWAP ${(Number(fresh.vwap_ready_ratio || 0) * 100).toFixed(1)}%`;
    document.getElementById('mx-promotion').textContent = stateText;
    document.getElementById('mx-expectancy').textContent = `expectancy ${expText}`;
    document.getElementById('mx-runtime-regime').textContent = runtime.current_regime || '—';
    document.getElementById('mx-runtime-detail').textContent = `score ${Number(runtime.regime_score || 0).toFixed(1)} · hard ${runtime.hard_shift_triggered ? 'Y' : 'N'}`;
    document.getElementById('mx-execution').textContent = Number(execution.execution_quality_score || 0).toFixed(2);
    document.getElementById('mx-permission').textContent = `${permission.strategy || '—'} ${permission.runtime_permission || '—'} ${permission.blocked_reason || ''}`;
  } catch (_) {
  }
}

initCandidateDrag();
connect();
refreshStrategyMetrics();
setInterval(refreshStrategyMetrics, 5000);
</script>
</body>
</html>
"""


# ------------------------------------------------------------------
# SSE 스트림
# ------------------------------------------------------------------

async def log_stream(request: Request):
    async def generator():
        # 1. 최근 N줄 히스토리 전송
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            history = [l.rstrip() for l in all_lines[-MAX_HISTORY:] if l.strip()]
            # 중복 라인 제거 (봇이 두 번씩 로깅하는 경우)
            seen: set[str] = set()
            deduped = []
            for l in history:
                if l not in seen:
                    seen.add(l)
                    deduped.append(l)
            import json
            yield {"event": "history", "data": json.dumps(deduped)}
        except FileNotFoundError:
            pass

        # 2. 새 줄 tail -f 스타일 스트리밍
        import json as _json
        last_inode = -1
        last_pos = 0

        try:
            stat = os.stat(LOG_FILE)
            last_inode = stat.st_ino
            last_pos = stat.st_size
        except FileNotFoundError:
            last_pos = 0

        seen_new: set[str] = set()

        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.3)

            try:
                stat = os.stat(LOG_FILE)
            except FileNotFoundError:
                await asyncio.sleep(1)
                continue

            # 로그 로테이션 감지
            if stat.st_ino != last_inode:
                last_inode = stat.st_ino
                last_pos = 0
                seen_new.clear()

            if stat.st_size < last_pos:
                last_pos = 0
                seen_new.clear()

            if stat.st_size > last_pos:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_pos)
                    new_data = f.read()
                    last_pos = f.tell()

                for raw in new_data.splitlines():
                    raw = raw.strip()
                    if not raw or raw in seen_new:
                        continue
                    seen_new.add(raw)
                    if len(seen_new) > 5000:
                        seen_new.clear()
                    yield {"event": "line", "data": _json.dumps(raw)}

    return EventSourceResponse(generator())


@app.get("/stream")
async def stream(request: Request):
    return await log_stream(request)


@app.get("/", response_class=HTMLResponse)
async def index():
    return _HTML


def _latest_diagnostics() -> dict:
    files = sorted(DIAGNOSTICS_DIR.glob("*.jsonl"))
    if not files:
        return {}
    wanted = {
        "regime_snapshot",
        "execution_quality",
        "runtime_permission",
        "microprice_snapshot",
        "depth_fill_estimate",
        "broker_reconcile",
        "orderbook_snapshot",
        "tick_merge_result",
        "pipeline_event",
        "gatekeeper_snapshot",
        "quote_health_snapshot",
        "latency_state",
        "orderbook_stability_snapshot",
        "candidate_provenance_snapshot",
        "buy_funnel_sentinel_report",
        "holding_exit_sentinel_report",
        "expected_edge_snapshot",
        "expected_vs_actual_edge",
        "runner_decision",
        "exit_profile_selected",
    }
    latest: dict = {}
    try:
        lines = files[-1].read_text(encoding="utf-8").splitlines()
    except Exception:
        return latest
    for line in reversed(lines[-2000:]):
        try:
            row = json.loads(line)
        except Exception:
            continue
        event_type = row.get("event_type")
        if event_type in wanted and event_type not in latest:
            latest[event_type] = row
        if len(latest) == len(wanted):
            break
    return latest


@app.get("/strategy-metrics")
async def strategy_metrics():
    reports = sorted(REPORT_DIR.glob("*.json"))
    report = {}
    if reports:
        try:
            report = json.loads(reports[-1].read_text(encoding="utf-8"))
        except Exception:
            report = {}
    promotion = {}
    if PROMOTION_STATE.exists():
        try:
            promotion = json.loads(PROMOTION_STATE.read_text(encoding="utf-8"))
        except Exception:
            promotion = {}
    latest = _latest_diagnostics()
    return {
        "report": report,
        "promotion": promotion,
        "latest": latest,
        "metrics": {
            "raw_candidates": (report.get("conversion_funnel") or {}).get("raw_scan_count", 0),
            "strategy_candidates": (report.get("conversion_funnel") or {}).get("strategy_candidate_count_by_strategy", {}),
            "signals": (report.get("conversion_funnel") or {}).get("strategy_signal_count_by_strategy", {}),
            "orders": (report.get("conversion_funnel") or {}).get("live_order_attempt_count", 0),
            "fills": (report.get("conversion_funnel") or {}).get("fill_count", 0),
            "top_reject_reasons": report.get("top_reject_reasons", {}),
            "feature_freshness": report.get("feature_freshness", {}),
            "microprice": latest.get("microprice_snapshot", {}),
            "depth_fill": latest.get("depth_fill_estimate", {}),
            "broker_reconcile": latest.get("broker_reconcile", {}),
            "orderbook_snapshot": latest.get("orderbook_snapshot", {}),
            "tick_merge_result": latest.get("tick_merge_result", {}),
            "pipeline_event": latest.get("pipeline_event", {}),
            "gatekeeper_snapshot": latest.get("gatekeeper_snapshot", {}),
            "quote_health": latest.get("quote_health_snapshot", {}),
            "latency_state": latest.get("latency_state", {}),
            "orderbook_stability": latest.get("orderbook_stability_snapshot", {}),
            "candidate_provenance": latest.get("candidate_provenance_snapshot", {}),
            "blocker_outcomes": report.get("blocker_outcomes", {}),
            "expected_vs_actual_edge": report.get("expected_vs_actual_edge", {}),
            "expected_edge": latest.get("expected_edge_snapshot", {}),
            "runner_decision": latest.get("runner_decision", {}),
            "exit_profile_selected": latest.get("exit_profile_selected", {}),
            "top_terminal_blocker": (
                next(iter((report.get("blocker_outcomes") or {}).get("terminal_blocker", {}) or {}), "")
            ),
            "shadow_expectancy": {
                k: v.get("net_expectancy", 0)
                for k, v in (report.get("strategy_stats") or {}).items()
            },
        },
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8765"))
    print(f"대시보드 시작: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
