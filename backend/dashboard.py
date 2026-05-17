"""
Meridian strategy dashboard — backend routes + self-contained HTML.

Three backtested strategies (quant, vader, finbert) are presented side-by-side
with their equity curves, headline metrics, recent closed trades, and the SPY
benchmark line.  Data is read from ``backtest/results/{strategy}/`` on every
request — no caching, since the CSVs are small and the dashboard is internal.

Paper-trading sections are currently stubs; once the per-strategy paper
harness lands they will pull from the same endpoints with ``mode=paper``.

To attach to the FastAPI app::

    from backend.dashboard import register_dashboard
    register_dashboard(app)

then visit ``http://localhost:8000/dashboard``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RESULTS_DIR = _REPO_ROOT / "backtest" / "results"

STRATEGIES = ("quant", "vader", "finbert")


def _read_metrics(strategy: str) -> dict[str, Any]:
    path = _RESULTS_DIR / strategy / "metrics.json"
    if not path.exists():
        return {"status": "no_results", "strategy": strategy}
    try:
        with open(path) as fh:
            return {"status": "ok", "strategy": strategy, **json.load(fh)}
    except Exception as exc:
        logger.warning("Failed to read metrics for %s: %s", strategy, exc)
        return {"status": "error", "strategy": strategy, "error": str(exc)}


def _read_curve(strategy: str, filename: str, downsample: int = 1) -> list[dict]:
    """Read an equity-curve CSV. Optionally take every Nth row for plotting speed."""
    path = _RESULTS_DIR / strategy / filename
    if not path.exists():
        return []
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if df.empty:
            return []
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"]).dt.strftime("%Y-%m-%d")
        if downsample > 1:
            df = df.iloc[::downsample].copy()
        return df[["ts", "equity"]].to_dict(orient="records")
    except Exception as exc:
        logger.warning("Failed to read %s/%s: %s", strategy, filename, exc)
        return []


def _read_trades(strategy: str, limit: int = 50) -> list[dict]:
    path = _RESULTS_DIR / strategy / "trades.csv"
    if not path.exists():
        return []
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if df.empty:
            return []
        cols_to_keep = [c for c in df.columns if c.lower() != "id"]
        df = df[cols_to_keep].tail(limit)
        return df.to_dict(orient="records")
    except Exception as exc:
        logger.warning("Failed to read trades for %s: %s", strategy, exc)
        return []


def get_strategy_payload(strategy: str, curve_downsample: int = 7) -> dict[str, Any]:
    """Aggregate metrics + equity curve + SPY benchmark + recent trades for one strategy."""
    if strategy not in STRATEGIES:
        raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy}")
    return {
        "strategy": strategy,
        "metrics":   _read_metrics(strategy),
        "equity":    _read_curve(strategy, "equity_curve.csv", downsample=curve_downsample),
        "benchmark": _read_curve(strategy, "spy_curve.csv",    downsample=curve_downsample),
        "trades":    _read_trades(strategy, limit=20),
    }


_DASHBOARD_HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Meridian — Strategy Dashboard</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.0\"></script>
  <script src=\"https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js\"></script>
  <style>
    :root {
      --bg: #0d1117; --panel: #161b22; --border: #30363d;
      --fg: #e6edf3; --muted: #8b949e;
      --good: #3fb950; --bad: #f85149; --accent: #58a6ff;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif; }
    header { padding: 18px 24px; border-bottom: 1px solid var(--border); }
    header h1 { margin: 0 0 4px 0; font-size: 22px; font-weight: 600; }
    header .sub { color: var(--muted); font-size: 13px; }
    .grid { display: grid; grid-template-columns: 1fr; gap: 16px; padding: 16px; }
    @media (min-width: 1100px) { .grid { grid-template-columns: repeat(3, 1fr); } }
    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
    .card h2 { margin: 0 0 4px 0; font-size: 16px; font-weight: 600; text-transform: capitalize; }
    .card .strategy-sub { color: var(--muted); font-size: 12px; margin-bottom: 12px; }
    .kpis { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 16px; margin-bottom: 12px; }
    .kpi { display: flex; flex-direction: column; }
    .kpi .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
    .kpi .value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .kpi .value.good { color: var(--good); }
    .kpi .value.bad { color: var(--bad); }
    .chart-wrap { position: relative; height: 220px; margin-bottom: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
    th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border); }
    th { color: var(--muted); font-weight: 500; text-transform: uppercase; font-size: 10px; letter-spacing: 0.04em; }
    .placeholder { color: var(--muted); font-style: italic; padding: 16px; text-align: center; }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; }
    .pill.live { background: rgba(63,185,80,0.12); color: var(--good); border: 1px solid rgba(63,185,80,0.4); }
    .pill.paper { background: rgba(88,166,255,0.12); color: var(--accent); border: 1px solid rgba(88,166,255,0.4); }
    .pill.stub { background: rgba(139,148,158,0.12); color: var(--muted); border: 1px solid rgba(139,148,158,0.3); }
    .section-title { padding: 16px 24px 0 24px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
  </style>
</head>
<body>
  <header>
    <h1>Meridian — Strategy Dashboard</h1>
    <div class=\"sub\">Three signal strategies on the 2010-2024 (FNSPID window: 2010-2023) universe. Data refreshes on load.</div>
  </header>

  <div class=\"section-title\">Backtest results</div>
  <div class=\"grid\" id=\"backtest-grid\"></div>

  <div class=\"section-title\">Paper trading <span class=\"pill stub\">stub</span></div>
  <div class=\"grid\" id=\"paper-grid\">
    <div class=\"card placeholder\">Paper harness not yet wired. Will mirror backtest layout once per-strategy live virtual portfolios are running.</div>
  </div>

<script>
const STRATEGIES = ['quant', 'vader', 'finbert'];

function fmtPct(x) { if (x == null || isNaN(x)) return '—'; return (x * 100).toFixed(1) + '%'; }
function fmtNum(x, d) { if (x == null || isNaN(x)) return '—'; return Number(x).toFixed(d == null ? 2 : d); }
function fmtX(x) { if (x == null || isNaN(x)) return '—'; return Number(x).toFixed(2) + 'x'; }
function fmtSigned(x) { if (x == null || isNaN(x)) return '—'; const v = Number(x); return (v >= 0 ? '+' : '') + v.toFixed(3); }
function colorClass(v, neutral) { if (v == null || isNaN(v)) return ''; if (neutral) return ''; return v >= 0 ? 'good' : 'bad'; }

async function loadStrategy(strategy) {
  const r = await fetch('/api/strategies/' + strategy);
  if (!r.ok) throw new Error(strategy + ': ' + r.status);
  return await r.json();
}

function renderCard(payload) {
  const m = payload.metrics || {};
  if (m.status !== 'ok') {
    return '<div class=\"card\"><h2>' + payload.strategy + '</h2><div class=\"placeholder\">No results yet (status: ' + (m.status || 'unknown') + ')</div></div>';
  }
  const fw = m.full_window || {};
  const bm = m.benchmark && m.benchmark.full_window ? m.benchmark.full_window : {};
  const excess = fw.excess_sharpe;
  const lastEq = payload.equity && payload.equity.length ? payload.equity[payload.equity.length - 1].equity : null;
  const initCash = m.parameters && m.parameters.initial_cash ? m.parameters.initial_cash : 1e6;
  const ret = lastEq != null ? (lastEq / initCash - 1) : null;

  const kpis = `
    <div class=\"kpis\">
      <div class=\"kpi\"><span class=\"label\">Sharpe</span><span class=\"value\">${fmtNum(fw.sharpe)}</span></div>
      <div class=\"kpi\"><span class=\"label\">SPY Sharpe</span><span class=\"value\">${fmtNum(bm.sharpe)}</span></div>
      <div class=\"kpi\"><span class=\"label\">Excess</span><span class=\"value ${colorClass(excess)}\">${fmtSigned(excess)}</span></div>
      <div class=\"kpi\"><span class=\"label\">Max DD</span><span class=\"value bad\">−${fmtPct(fw.max_drawdown)}</span></div>
      <div class=\"kpi\"><span class=\"label\">Hit rate</span><span class=\"value\">${fmtPct(fw.hit_rate)}</span></div>
      <div class=\"kpi\"><span class=\"label\">Trades</span><span class=\"value\">${fw.trade_count != null ? fw.trade_count : '—'}</span></div>
    </div>`;

  let tradesHtml = '<div class=\"placeholder\">No closed trades yet.</div>';
  if (payload.trades && payload.trades.length) {
    const cols = Object.keys(payload.trades[0]).slice(0, 5);
    tradesHtml = '<table><thead><tr>' + cols.map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>' +
      payload.trades.slice(-8).map(row =>
        '<tr>' + cols.map(c => '<td>' + (row[c] == null ? '' : String(row[c]).slice(0, 18)) + '</td>').join('') + '</tr>'
      ).join('') + '</tbody></table>';
  }

  const startDate = m.parameters ? m.parameters.start : '';
  const endDate = m.parameters ? m.parameters.end : '';
  return `
    <div class=\"card\">
      <h2>${payload.strategy} <span class=\"pill paper\">backtest</span></h2>
      <div class=\"strategy-sub\">${startDate} → ${endDate} · ${m.parameters && m.parameters.universe_size ? m.parameters.universe_size + ' symbols' : ''}</div>
      ${kpis}
      <div class=\"chart-wrap\"><canvas id=\"chart-${payload.strategy}\"></canvas></div>
      ${tradesHtml}
    </div>`;
}

function makeChart(canvasId, payload) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const ds = [];
  if (payload.equity && payload.equity.length) {
    ds.push({
      label: 'strategy',
      data: payload.equity.map(p => ({ x: p.ts, y: p.equity })),
      borderColor: '#58a6ff', borderWidth: 1.5, pointRadius: 0, tension: 0.1, fill: false,
    });
  }
  if (payload.benchmark && payload.benchmark.length) {
    ds.push({
      label: 'SPY',
      data: payload.benchmark.map(p => ({ x: p.ts, y: p.equity })),
      borderColor: '#8b949e', borderWidth: 1, borderDash: [4, 4], pointRadius: 0, tension: 0.1, fill: false,
    });
  }
  new Chart(ctx, {
    type: 'line',
    data: { datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { labels: { color: '#e6edf3', boxWidth: 12, font: { size: 11 } } } },
      scales: {
        x: { type: 'time', time: { unit: 'year' }, ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#21262d' } },
        y: { ticks: { color: '#8b949e', font: { size: 10 }, callback: v => '$' + (v / 1e6).toFixed(1) + 'M' }, grid: { color: '#21262d' } },
      },
    },
  });
}

(async function init() {
  const grid = document.getElementById('backtest-grid');
  const payloads = await Promise.all(STRATEGIES.map(s => loadStrategy(s).catch(e => ({ strategy: s, metrics: { status: 'error', error: e.message } }))));
  grid.innerHTML = payloads.map(renderCard).join('');
  for (const p of payloads) makeChart('chart-' + p.strategy, p);
})();
</script>
</body>
</html>
"""


def register_dashboard(app: FastAPI) -> None:
    """Attach dashboard HTML route + per-strategy JSON endpoints to *app*."""

    @app.get("/api/strategies/{strategy}")
    def api_strategy(strategy: str):
        return get_strategy_payload(strategy)

    @app.get("/api/strategies")
    def api_all_strategies():
        return {s: get_strategy_payload(s) for s in STRATEGIES}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return HTMLResponse(_DASHBOARD_HTML)
