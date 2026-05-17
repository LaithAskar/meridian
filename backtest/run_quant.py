"""
End-to-end quant strategy backtest over the full 2010-2024 window.

Usage (from repo root):
    python -m backtest.run_quant
    python -m backtest.run_quant --positions 10 --cash 1000000

Outputs written to backtest/results/quant/:
    equity_curve.csv  — daily equity, cash, num_positions (DatetimeIndex)
    trades.csv        — closed-trade log
    metrics.json      — Sharpe / max DD / hit rate / etc. per window & regime
    spy_curve.csv     — SPY buy-and-hold equity (benchmark for Phase 4)

Regime splits follow DESIGN.md:
    Pre-COVID  : 2010-01-01 → 2020-02-29
    Post-COVID : 2020-03-01 → 2024-12-31
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.data import fetch_bars
from backtest.engine import Engine
from backtest.metrics import (
    avg_holding_period,
    avg_win_loss,
    benchmark_metrics,
    cagr,
    excess_sharpe,
    exposure,
    hit_rate,
    max_drawdown,
    sharpe,
    sharpe_se,
    total_return,
)
from backtest.signals.quant import QuantStrategy
from backtest.universe import UNIVERSE_2010, tradable_universe

_LOG = logging.getLogger(__name__)

FULL_START = date(2010, 1, 1)
FULL_END = date(2024, 12, 31)
PRE_COVID_END = date(2020, 2, 29)    # pre-COVID window ends here (inclusive)
POST_COVID_START = date(2020, 3, 1)  # post-COVID window starts here

_RESULTS_DIR = Path(__file__).resolve().parent / "results" / "quant"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_spy_vix(start: date, end: date) -> tuple[pd.Series, pd.Series]:
    """
    Fetch SPY and VIX daily close series from yfinance (cached).

    Returns (spy_close, vix_close) as DatetimeIndex pd.Series.
    Returns empty Series on fetch failure; QuantStrategy falls back to
    neutral regime throughout in that case.
    """
    spy_bars = fetch_bars(["SPY"], start, end)
    vix_bars = fetch_bars(["^VIX"], start, end)

    if spy_bars.empty:
        _LOG.warning("No SPY data — regime detection defaults to neutral throughout")
        spy_close: pd.Series = pd.Series(dtype=float)
    else:
        spy_close = spy_bars.xs("SPY", level="symbol")["close"]
        spy_close.index = pd.DatetimeIndex(spy_close.index)

    if vix_bars.empty:
        _LOG.warning("No VIX data — VIX defaults to 20 throughout")
        vix_close: pd.Series = pd.Series(dtype=float)
    else:
        vix_close = vix_bars.xs("^VIX", level="symbol")["close"]
        vix_close.index = pd.DatetimeIndex(vix_close.index)

    return spy_close, vix_close


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def _nan_to_none(x: Any) -> Any:
    """Convert float NaN to None so the result serialises cleanly to JSON."""
    if isinstance(x, float) and math.isnan(x):
        return None
    return x


def metrics_for_window(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    years: float,
    spy_returns: pd.Series | None = None,
) -> dict[str, Any]:
    """
    Compute all DESIGN.md-specified metrics for one backtest window.

    Parameters
    ----------
    equity_curve : Engine output, optionally date-sliced; must have 'equity' column
    trades       : Engine output, optionally date-sliced; may be empty
    years        : window length in years (used for CAGR)
    spy_returns  : optional SPY daily return series for the same window;
                   when provided, adds 'excess_sharpe' (strategy − SPY)

    Returns
    -------
    Dict with keys:
        sharpe, sharpe_se, excess_sharpe, max_drawdown, hit_rate, avg_win,
        avg_loss, win_loss_ratio, avg_holding_days, trade_count, exposure,
        total_return, cagr
    NaN values are converted to None for JSON-safe serialisation.
    excess_sharpe is None when spy_returns is not provided or is empty.
    """
    if equity_curve.empty:
        return {"error": "empty_window"}

    returns = equity_curve["equity"].pct_change().dropna()
    wl = avg_win_loss(trades)
    ahp = avg_holding_period(trades)

    xs = (
        round(excess_sharpe(returns, spy_returns), 4)
        if spy_returns is not None and not spy_returns.empty
        else None
    )

    return {
        "sharpe":           round(sharpe(returns), 4),
        "sharpe_se":        round(sharpe_se(returns), 4),
        "excess_sharpe":    xs,
        "max_drawdown":     round(max_drawdown(equity_curve), 4),
        "hit_rate":         round(hit_rate(trades), 4),
        "avg_win":          _nan_to_none(None if math.isnan(wl["avg_win"]) else round(wl["avg_win"], 2)),
        "avg_loss":         _nan_to_none(None if math.isnan(wl["avg_loss"]) else round(wl["avg_loss"], 2)),
        "win_loss_ratio":   _nan_to_none(None if math.isnan(wl["win_loss_ratio"]) else round(wl["win_loss_ratio"], 4)),
        "avg_holding_days": _nan_to_none(None if math.isnan(ahp) else round(ahp, 2)),
        "trade_count":      len(trades),
        "exposure":         round(exposure(equity_curve), 4),
        "total_return":     round(total_return(equity_curve), 4),
        "cagr":             round(cagr(equity_curve, years), 4) if years > 0 else None,
    }


def slice_window(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Slice equity_curve and trades to the [start, end] window.

    equity_curve is filtered by its DatetimeIndex.
    trades are filtered by exit_ts (the timestamp that closes the trade).
    """
    start_ts = pd.Timestamp(start) if start is not None else pd.Timestamp.min
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp.max

    ec = equity_curve.loc[
        (equity_curve.index >= start_ts) & (equity_curve.index <= end_ts)
    ]

    if trades.empty:
        return ec, trades

    exit_col = pd.to_datetime(trades["exit_ts"])
    tr = trades.loc[(exit_col >= start_ts) & (exit_col <= end_ts)]
    return ec, tr


# ---------------------------------------------------------------------------
# SPY benchmark helpers
# ---------------------------------------------------------------------------

def _spy_slice(spy_close: pd.Series, start: date, end: date) -> pd.Series:
    """Return spy_close clipped to [start, end] (empty if spy_close is empty)."""
    if spy_close.empty:
        return spy_close
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return spy_close.loc[(spy_close.index >= s) & (spy_close.index <= e)]


def _spy_returns_per_window(
    spy_close: pd.Series,
    start: date,
    end: date,
    pre_end: date,
    post_start: date,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Return (full, pre-COVID, post-COVID) SPY daily-return Series for use in
    excess_sharpe.  Empty Series when spy_close is empty.
    """
    _empty = pd.Series(dtype=float)
    if spy_close.empty:
        return _empty, _empty, _empty

    def _rets(s: date, e: date) -> pd.Series:
        sliced = _spy_slice(spy_close, s, e)
        return sliced.pct_change().dropna() if not sliced.empty else _empty

    return _rets(start, end), _rets(start, pre_end), _rets(post_start, end)


def _benchmark_block(
    spy_close: pd.Series,
    start: date,
    end: date,
    full_years: float,
    pre_years: float,
    post_years: float,
) -> dict[str, Any] | None:
    """
    Build the 'benchmark' sub-dict for metrics.json.

    Returns None when SPY data is unavailable.  Structure:
        {name, full_window: {sharpe, max_drawdown, total_return, cagr},
         pre_covid: {...}, post_covid: {...}}
    """
    if spy_close.empty:
        return None

    return {
        "name": "SPY buy-and-hold",
        "full_window": benchmark_metrics(_spy_slice(spy_close, start, end), full_years),
        "pre_covid":   benchmark_metrics(_spy_slice(spy_close, start, PRE_COVID_END), pre_years),
        "post_covid":  benchmark_metrics(_spy_slice(spy_close, POST_COVID_START, end), post_years),
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_quant_backtest(
    universe: list[str] | None = None,
    start: date = FULL_START,
    end: date = FULL_END,
    max_positions: int = 10,
    initial_cash: float = 1_000_000.0,
    output_dir: Path = _RESULTS_DIR,
) -> dict[str, Any]:
    """
    Run the QuantStrategy end-to-end and save results to *output_dir*.

    Parameters
    ----------
    universe      : tickers to trade; defaults to UNIVERSE_2010 (100 names)
    start / end   : inclusive backtest window; defaults to 2010-01-01 / 2024-12-31
    max_positions : max concurrent long positions (equal-weight sizing)
    initial_cash  : starting NAV in USD
    output_dir    : destination for CSV + JSON outputs

    Returns
    -------
    The metrics dict (identical content written to metrics.json).
    """
    if universe is None:
        # Use tradable_universe (UNIVERSE_2010 minus KNOWN_NO_DATA) so the
        # engine doesn't silently consume wrong-company data for tickers
        # whose original 2010-era issuer was acquired but whose symbol has
        # since been re-used.  Added 2026-05-17 per audit A.3 §3.1.
        universe = list(tradable_universe())

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Regime data ────────────────────────────────────────────────────────────
    _LOG.info("Fetching SPY + VIX for regime detection (%s → %s)...", start, end)
    spy_close, vix_close = load_spy_vix(start, end)

    # ── Engine run ─────────────────────────────────────────────────────────────
    _LOG.info(
        "Running QuantStrategy: %d symbols, %s → %s, max_positions=%d",
        len(universe), start, end, max_positions,
    )
    strategy = QuantStrategy(
        max_positions=max_positions,
        spy_close=spy_close if not spy_close.empty else None,
        vix_close=vix_close if not vix_close.empty else None,
    )
    engine = Engine(
        strategy=strategy,
        universe=universe,
        start=start,
        end=end,
        initial_cash=initial_cash,
        max_positions=max_positions,
    )
    result = engine.run()
    _LOG.info(
        "Engine done: %d trading days, %d closed trades",
        len(result.equity_curve), len(result.trades),
    )

    # ── Persist raw outputs ────────────────────────────────────────────────────
    result.equity_curve.to_csv(output_dir / "equity_curve.csv")
    result.trades.to_csv(output_dir / "trades.csv", index=False)
    _LOG.info("Wrote equity_curve.csv and trades.csv")

    # SPY buy-and-hold for Phase 4 benchmark comparison
    if not spy_close.empty:
        spy_bah = (spy_close / float(spy_close.iloc[0])) * initial_cash
        spy_df = spy_bah.rename("equity").to_frame()
        spy_df.index.name = "ts"
        spy_df.to_csv(output_dir / "spy_curve.csv")
        _LOG.info("Wrote spy_curve.csv")

    # ── Regime metric slices ───────────────────────────────────────────────────
    pre_ec, pre_trades   = slice_window(result.equity_curve, result.trades, end=PRE_COVID_END)
    post_ec, post_trades = slice_window(result.equity_curve, result.trades, start=POST_COVID_START)

    full_years = (end - start).days / 365.25
    pre_years  = (PRE_COVID_END - start).days / 365.25
    post_years = (end - POST_COVID_START).days / 365.25

    # SPY returns sliced to each window, for excess-Sharpe computation
    full_spy_rets, pre_spy_rets, post_spy_rets = _spy_returns_per_window(
        spy_close, start, end, PRE_COVID_END, POST_COVID_START
    )

    metrics: dict[str, Any] = {
        "run_date": date.today().isoformat(),
        "parameters": {
            "universe_size":    len(universe),
            "start":            start.isoformat(),
            "end":              end.isoformat(),
            "max_positions":    max_positions,
            "initial_cash":     initial_cash,
            "slippage_bps":     5,
            "min_history_bars": 60,
        },
        "full_window": metrics_for_window(
            result.equity_curve, result.trades, full_years, full_spy_rets
        ),
        "pre_covid":  metrics_for_window(pre_ec, pre_trades, pre_years, pre_spy_rets),
        "post_covid": metrics_for_window(post_ec, post_trades, post_years, post_spy_rets),
        "benchmark":  _benchmark_block(spy_close, start, end, full_years, pre_years, post_years),
    }

    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w") as fh:
        json.dump(metrics, fh, indent=2)
    _LOG.info("Wrote metrics.json to %s", output_dir)

    return metrics


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Run quant backtest end-to-end")
    parser.add_argument(
        "--positions", type=int, default=10, metavar="N",
        help="max concurrent positions (default: 10)",
    )
    parser.add_argument(
        "--cash", type=float, default=1_000_000.0, metavar="USD",
        help="initial cash in USD (default: 1,000,000)",
    )
    args = parser.parse_args()

    result_metrics = run_quant_backtest(
        max_positions=args.positions,
        initial_cash=args.cash,
    )
    print(json.dumps(result_metrics, indent=2))
