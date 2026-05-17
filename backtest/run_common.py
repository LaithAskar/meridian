"""
Shared helpers for the end-to-end backtest run scripts (run_quant,
run_vader, run_finbert).

This module exists to avoid copy-pasting metric / SPY-benchmark logic across
the three runners.  ``run_quant.py`` predates it and currently defines its
own copies; that file is audit-pending so it is not modified here.  After
the audit gate clears, ``run_quant.py`` can be refactored to import from
this module too.

What lives here
---------------
- ``metrics_for_window`` — apply all DESIGN.md-specified metrics to one
  (equity_curve, trades) window slice.
- ``slice_window`` — restrict (equity_curve, trades) to a date window.
- ``benchmark_block`` — build the SPY buy-and-hold sub-dict for metrics.json.
- ``spy_returns_for_windows`` — slice SPY daily returns to the three windows.
- ``load_spy_close`` — fetch SPY close series via the existing yfinance loader.
- ``_nan_to_none`` — JSON-safe NaN handling.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Optional

import pandas as pd

from backtest.data import fetch_bars
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


def _nan_to_none(x: Any) -> Any:
    """Convert float NaN to None so the result serialises cleanly to JSON."""
    if isinstance(x, float) and math.isnan(x):
        return None
    return x


def metrics_for_window(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    years: float,
    spy_returns: Optional[pd.Series] = None,
) -> dict[str, Any]:
    """Compute all DESIGN.md-specified metrics for one window slice.

    Mirrors the dict structure produced by ``backtest.run_quant`` so the
    three signal sources are directly comparable.
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
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Restrict (equity_curve, trades) to the date window [start, end]."""
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


def load_spy_close(start: date, end: date) -> pd.Series:
    """Fetch SPY daily close prices via yfinance (cached).

    Returns an empty Series on fetch failure — caller should handle the
    "no benchmark available" case.
    """
    bars = fetch_bars(["SPY"], start, end)
    if bars.empty:
        return pd.Series(dtype=float)
    s = bars.xs("SPY", level="symbol")["close"]
    s.index = pd.DatetimeIndex(s.index)
    return s


def _spy_slice(spy_close: pd.Series, start: date, end: date) -> pd.Series:
    if spy_close.empty:
        return spy_close
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return spy_close.loc[(spy_close.index >= s) & (spy_close.index <= e)]


def spy_returns_for_windows(
    spy_close: pd.Series,
    start: date,
    end: date,
    pre_end: date,
    post_start: date,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (full, pre, post) SPY daily-return Series for excess_sharpe.

    Empty Series when ``spy_close`` is empty.
    """
    _empty = pd.Series(dtype=float)
    if spy_close.empty:
        return _empty, _empty, _empty

    def _rets(s: date, e: date) -> pd.Series:
        sliced = _spy_slice(spy_close, s, e)
        return sliced.pct_change().dropna() if not sliced.empty else _empty

    return _rets(start, end), _rets(start, pre_end), _rets(post_start, end)


def benchmark_block(
    spy_close: pd.Series,
    start: date,
    end: date,
    pre_end: date,
    post_start: date,
    full_years: float,
    pre_years: float,
    post_years: float,
) -> Optional[dict[str, Any]]:
    """Build the ``benchmark`` sub-dict for metrics.json.

    Returns None when SPY data is unavailable.
    """
    if spy_close.empty:
        return None
    return {
        "name": "SPY buy-and-hold",
        "full_window": benchmark_metrics(_spy_slice(spy_close, start, end), full_years),
        "pre_covid":   benchmark_metrics(_spy_slice(spy_close, start, pre_end), pre_years),
        "post_covid":  benchmark_metrics(_spy_slice(spy_close, post_start, end), post_years),
    }
