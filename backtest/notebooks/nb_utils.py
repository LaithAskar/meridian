"""
Utility functions for results.ipynb.

These pure-Python functions are separated from the notebook so they can be
unit-tested without executing the notebook.  The notebook imports from here;
backtest/tests/test_nb_utils.py covers the logic directly.

Data contracts (same shapes produced by Engine.run() and run_quant.py):

    equity_curve : pd.DataFrame  — DatetimeIndex × {equity, cash, num_positions}
    trades       : pd.DataFrame  — {symbol, entry_ts, exit_ts, qty,
                                     entry_price, exit_price, pnl, holding_days}
    metrics      : dict          — {run_date, parameters, full_window,
                                     pre_covid, post_covid}
                     each window : {sharpe, sharpe_se, max_drawdown, hit_rate,
                                     avg_win, avg_loss, win_loss_ratio,
                                     avg_holding_days, trade_count, exposure,
                                     total_return, cagr}
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Public constants (imported by the notebook for labelling)
# ---------------------------------------------------------------------------

STRATEGIES: tuple[str, ...] = ("quant", "vader", "finbert")

WINDOW_LABELS: dict[str, str] = {
    "full_window": "Full (2010–2024)",
    "pre_covid":   "Pre-COVID (2010–Feb 2020)",
    "post_covid":  "Post-COVID (Mar 2020–2024)",
}

METRIC_KEYS: list[str] = [
    "sharpe", "sharpe_se", "excess_sharpe", "max_drawdown", "hit_rate",
    "avg_win", "avg_loss", "win_loss_ratio", "avg_holding_days",
    "trade_count", "exposure", "total_return", "cagr",
]

# Metrics that a passive buy-and-hold benchmark can report (no trades).
BENCHMARK_METRIC_KEYS: list[str] = [
    "sharpe", "max_drawdown", "total_return", "cagr",
]

METRIC_LABELS: dict[str, str] = {
    "sharpe":           "Sharpe",
    "sharpe_se":        "Sharpe SE",
    "excess_sharpe":    "Excess Sharpe (vs SPY)",
    "max_drawdown":     "Max Drawdown",
    "hit_rate":         "Hit Rate",
    "avg_win":          "Avg Win ($)",
    "avg_loss":         "Avg Loss ($)",
    "win_loss_ratio":   "Win/Loss Ratio",
    "avg_holding_days": "Avg Hold (days)",
    "trade_count":      "# Trades",
    "exposure":         "% Time in Market",
    "total_return":     "Total Return",
    "cagr":             "CAGR",
}

# Format strings are intentionally percentage-friendly: pass raw fractions
# (e.g. 0.12) for the "%" formats — Python's format() does the ×100 itself.
METRIC_FORMATS: dict[str, str] = {
    "sharpe":           ".3f",
    "sharpe_se":        ".3f",
    "excess_sharpe":    ".3f",
    "max_drawdown":     ".1%",
    "hit_rate":         ".1%",
    "avg_win":          ",.0f",
    "avg_loss":         ",.0f",
    "win_loss_ratio":   ".2f",
    "avg_holding_days": ".1f",
    "trade_count":      ",.0f",
    "exposure":         ".1%",
    "total_return":     ".1%",
    "cagr":             ".1%",
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_strategy_results(strategy: str, base_dir: Path) -> dict[str, Any] | None:
    """
    Load results for one strategy from *base_dir*/<strategy>/.

    All three artefacts (equity_curve.csv, trades.csv, metrics.json) must
    exist; if any is missing, return None so the notebook can display a
    "blocked / not run yet" placeholder instead of raising.
    """
    result_dir = base_dir / strategy
    equity_path = result_dir / "equity_curve.csv"
    trades_path = result_dir / "trades.csv"
    metrics_path = result_dir / "metrics.json"

    if not (equity_path.exists() and trades_path.exists() and metrics_path.exists()):
        return None

    equity_curve = pd.read_csv(equity_path, index_col="ts", parse_dates=True)
    trades = pd.read_csv(trades_path, parse_dates=["entry_ts", "exit_ts"])
    with open(metrics_path) as fh:
        metrics = json.load(fh)

    return {"equity_curve": equity_curve, "trades": trades, "metrics": metrics}


def load_spy_results(base_dir: Path) -> pd.DataFrame | None:
    """
    Load the SPY buy-and-hold equity curve saved by run_quant.py.

    The file lives at base_dir/quant/spy_curve.csv.  Returns None if missing.
    """
    spy_path = base_dir / "quant" / "spy_curve.csv"
    if not spy_path.exists():
        return None
    return pd.read_csv(spy_path, index_col="ts", parse_dates=True)


def load_benchmark_metrics(base_dir: Path) -> dict[str, Any] | None:
    """
    Load SPY benchmark metrics from backtest/results/quant/metrics.json.

    Returns the ``benchmark`` sub-dict (or None if unavailable), with shape::

        {
            "name": "SPY buy-and-hold",
            "full_window":  {"sharpe": ..., "max_drawdown": ..., "total_return": ..., "cagr": ...},
            "pre_covid":    {...},
            "post_covid":   {...},
        }

    ``None`` is returned when the quant run has not yet been executed, when
    the network policy blocked the data fetch, or when the SPY data was
    unavailable during the run.
    """
    metrics_path = base_dir / "quant" / "metrics.json"
    if not metrics_path.exists():
        return None
    with open(metrics_path) as fh:
        data = json.load(fh)
    return data.get("benchmark")


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def normalise_equity(equity_curve: pd.DataFrame, base: float = 100.0) -> pd.Series:
    """
    Rebase equity to *base* so strategies with different initial cash can be
    compared on one chart.

    Returns a DatetimeIndex pd.Series.  Empty input → empty series.
    Zero initial equity → series unchanged (avoids ZeroDivisionError).
    """
    eq: pd.Series = equity_curve["equity"]
    if eq.empty:
        return eq
    first = float(eq.iloc[0])
    if first == 0.0:
        return eq
    return eq / first * base


def compute_drawdown_series(equity_curve: pd.DataFrame) -> pd.Series:
    """
    Running peak-to-trough drawdown as a fraction ≤ 0.

    E.g. −0.25 means the portfolio is 25% below its running high-water mark.
    Negate for plotting on a positive axis if preferred.
    """
    eq: pd.Series = equity_curve["equity"]
    running_max = eq.cummax()
    return (eq - running_max) / running_max


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_metric_val(val: Any, metric: str) -> str:
    """
    Format *val* for human-readable display using the metric's registered
    format string.  Returns the em-dash '—' for None and NaN.
    """
    if val is None:
        return "—"
    if isinstance(val, float) and math.isnan(val):
        return "—"
    fmt = METRIC_FORMATS.get(metric, "g")
    try:
        return format(float(val), fmt)
    except (ValueError, TypeError):
        return str(val)


# ---------------------------------------------------------------------------
# Comparison builders
# ---------------------------------------------------------------------------

def build_metrics_comparison(
    all_results: dict[str, dict[str, Any] | None],
    window: str = "full_window",
    benchmark: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Build a (metric × strategy) comparison DataFrame for one window.

    Parameters
    ----------
    all_results : {strategy_name: results_dict_or_None}
                  None entries are treated as "not available".
    window      : 'full_window', 'pre_covid', or 'post_covid'
    benchmark   : optional SPY benchmark dict from load_benchmark_metrics().
                  When provided, a 'SPY B&H' column is appended.  Only
                  BENCHMARK_METRIC_KEYS are populated; trade-based rows are None.

    Returns
    -------
    DataFrame indexed by metric label, columns = capitalised strategy names
    (plus 'SPY B&H' when benchmark is supplied).
    Missing strategy data appears as None (not NaN) so callers can
    distinguish "no data" from a genuinely-zero metric.
    """
    rows: list[dict] = []
    for metric in METRIC_KEYS:
        row: dict[str, Any] = {"Metric": METRIC_LABELS.get(metric, metric)}
        for strategy, results in all_results.items():
            if results is None:
                row[strategy.capitalize()] = None
            else:
                window_data = results.get("metrics", {}).get(window, {})
                row[strategy.capitalize()] = window_data.get(metric)
        if benchmark is not None:
            window_data = benchmark.get(window, {})
            # Only report metrics a passive benchmark can provide
            row["SPY B&H"] = window_data.get(metric) if metric in BENCHMARK_METRIC_KEYS else None
        rows.append(row)

    return pd.DataFrame(rows).set_index("Metric")


def regime_sharpe_df(
    all_results: dict[str, dict[str, Any] | None],
    benchmark: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Build a (strategy × regime) Sharpe comparison table.

    Returns a DataFrame with WINDOW_LABELS values as columns and capitalised
    strategy names as the index.  Blocked/missing strategies → None.

    Parameters
    ----------
    all_results : {strategy_name: results_dict_or_None}
    benchmark   : optional SPY benchmark dict from load_benchmark_metrics().
                  When provided, a 'SPY B&H' row is appended for reference.
    """
    records: list[dict] = []
    for strategy, results in all_results.items():
        row: dict[str, Any] = {"Strategy": strategy.capitalize()}
        if results is None:
            for lbl in WINDOW_LABELS.values():
                row[lbl] = None
        else:
            m = results.get("metrics", {})
            for wk, lbl in WINDOW_LABELS.items():
                row[lbl] = m.get(wk, {}).get("sharpe")
        records.append(row)

    if benchmark is not None:
        spy_row: dict[str, Any] = {"Strategy": "SPY B&H"}
        for wk, lbl in WINDOW_LABELS.items():
            spy_row[lbl] = benchmark.get(wk, {}).get("sharpe")
        records.append(spy_row)

    return pd.DataFrame(records).set_index("Strategy")
