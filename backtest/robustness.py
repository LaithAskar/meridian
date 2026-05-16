"""
Robustness checks for the Meridian quant backtest.

Three independent checks, each addressing a different interview-grade question:

1. parameter_sensitivity
   "Is your Sharpe stable, or did you overfit max_positions?"
   → Grid-search over max_positions; report Sharpe / drawdown per value.

2. walk_forward
   "Did the strategy work in every period, or just one lucky stretch?"
   → Split [start, end] into n_folds consecutive windows; run the backtest
     independently on each; report per-fold Sharpe and max drawdown.

3. monte_carlo_trades
   "Is the edge real, or driven by a handful of outlier trades?"
   → Bootstrap-resample closed trades with replacement n_sims times; compute
     trade-level Sharpe for each resample; report the distribution and a
     one-sided p-value for H₀: edge ≤ 0.

All three functions are offline-testable: the engine calls are isolated in
the private _run_engine helper so tests can monkeypatch it without hitting
the network.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backtest.engine import Engine
from backtest.run_quant import metrics_for_window
from backtest.signals.quant import QuantStrategy

_POSITIONS_GRID_DEFAULT: list[int] = [5, 10, 15, 20]
_N_FOLDS_DEFAULT: int = 5
_N_SIMS_DEFAULT: int = 1_000


# ---------------------------------------------------------------------------
# Internal engine runner (monkeypatched in tests)
# ---------------------------------------------------------------------------

def _run_engine(
    universe: list[str],
    start: date,
    end: date,
    max_positions: int,
    initial_cash: float,
    spy_close: pd.Series | None,
    vix_close: pd.Series | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Construct and run the Engine for one (start, end, max_positions) combo.

    Returns (equity_curve, trades) — the two DataFrames from BacktestResult.
    Isolated here so tests can monkeypatch this function without touching
    Engine or fetch_bars directly.
    """
    strategy = QuantStrategy(
        max_positions=max_positions,
        spy_close=spy_close if spy_close is not None and not spy_close.empty else None,
        vix_close=vix_close if vix_close is not None and not vix_close.empty else None,
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
    return result.equity_curve, result.trades


# ---------------------------------------------------------------------------
# 1. Parameter sensitivity
# ---------------------------------------------------------------------------

def parameter_sensitivity(
    universe: list[str],
    start: date,
    end: date,
    initial_cash: float = 1_000_000.0,
    positions_grid: list[int] | None = None,
    spy_close: pd.Series | None = None,
    vix_close: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Grid-search over max_positions to measure parameter sensitivity.

    For each value in positions_grid, runs the full quant strategy and
    captures Sharpe, Sharpe SE, max drawdown, CAGR, total return, and
    trade count.  Stable Sharpe across the grid means the strategy is
    not overfit to a single position-count choice.

    Parameters
    ----------
    universe       : tickers to trade
    start, end     : backtest window (inclusive)
    initial_cash   : starting NAV in USD
    positions_grid : max_positions values to sweep (default [5, 10, 15, 20])
    spy_close      : optional SPY close series for regime detection
    vix_close      : optional VIX close series for regime detection

    Returns
    -------
    DataFrame indexed by max_positions with columns:
        sharpe, sharpe_se, max_drawdown, cagr, total_return, trade_count
    """
    if positions_grid is None:
        positions_grid = _POSITIONS_GRID_DEFAULT

    years = (end - start).days / 365.25
    rows = []
    for n in positions_grid:
        ec, trades = _run_engine(universe, start, end, n, initial_cash, spy_close, vix_close)
        m = metrics_for_window(ec, trades, years)
        rows.append({
            "max_positions": n,
            "sharpe":        m.get("sharpe"),
            "sharpe_se":     m.get("sharpe_se"),
            "max_drawdown":  m.get("max_drawdown"),
            "cagr":          m.get("cagr"),
            "total_return":  m.get("total_return"),
            "trade_count":   m.get("trade_count"),
        })
    return pd.DataFrame(rows).set_index("max_positions")


# ---------------------------------------------------------------------------
# 2. Walk-forward window
# ---------------------------------------------------------------------------

def _split_folds(start: date, end: date, n: int) -> list[tuple[date, date]]:
    """
    Divide [start, end] into n approximately equal consecutive folds.

    The last fold absorbs any remainder so the full date range is covered.
    Returns a list of (fold_start, fold_end) pairs (both ends inclusive).
    """
    if n < 1:
        raise ValueError(f"n must be ≥ 1; got {n}")

    total_days = (end - start).days
    fold_days = total_days // n
    folds: list[tuple[date, date]] = []
    for i in range(n):
        fs = start + timedelta(days=i * fold_days)
        fe = end if i == n - 1 else start + timedelta(days=(i + 1) * fold_days - 1)
        folds.append((fs, fe))
    return folds


def walk_forward(
    universe: list[str],
    start: date,
    end: date,
    max_positions: int = 10,
    initial_cash: float = 1_000_000.0,
    n_folds: int = _N_FOLDS_DEFAULT,
    spy_close: pd.Series | None = None,
    vix_close: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Time-period consistency check via consecutive out-of-sample folds.

    Splits [start, end] into n_folds non-overlapping windows and runs the
    backtest independently on each.  Because the quant strategy has no
    fitted parameters (all signals are computed from rolling history at
    runtime), each fold is a true out-of-sample test.  Positive Sharpe in
    most folds demonstrates the edge is not confined to one lucky stretch.

    Parameters
    ----------
    universe      : tickers to trade
    start, end    : full backtest window (inclusive)
    max_positions : concurrent positions cap (fixed across folds)
    initial_cash  : starting NAV for EACH fold (resets per fold so fold
                    Sharpes are comparable regardless of fold P&L)
    n_folds       : number of consecutive time windows (default 5)
    spy_close     : optional SPY close series for regime detection
    vix_close     : optional VIX close series for regime detection

    Returns
    -------
    DataFrame indexed by fold (0..n_folds-1) with columns:
        fold_start, fold_end, years, sharpe, sharpe_se, max_drawdown,
        cagr, total_return, trade_count
    """
    folds = _split_folds(start, end, n_folds)
    rows = []
    for i, (fs, fe) in enumerate(folds):
        years = max((fe - fs).days / 365.25, 1e-6)
        ec, trades = _run_engine(universe, fs, fe, max_positions, initial_cash, spy_close, vix_close)
        m = metrics_for_window(ec, trades, years)
        rows.append({
            "fold":         i,
            "fold_start":   fs.isoformat(),
            "fold_end":     fe.isoformat(),
            "years":        round(years, 2),
            "sharpe":       m.get("sharpe"),
            "sharpe_se":    m.get("sharpe_se"),
            "max_drawdown": m.get("max_drawdown"),
            "cagr":         m.get("cagr"),
            "total_return": m.get("total_return"),
            "trade_count":  m.get("trade_count"),
        })
    return pd.DataFrame(rows).set_index("fold")


# ---------------------------------------------------------------------------
# 3. Monte Carlo on trade ordering
# ---------------------------------------------------------------------------

def _trade_sharpe(returns: np.ndarray, annualisation: float) -> float:
    """Annualised Sharpe of a trade-return array. Returns 0.0 if std is zero."""
    if len(returns) < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std == 0.0:
        return 0.0
    return float(np.mean(returns) / std) * annualisation


def monte_carlo_trades(
    trades: pd.DataFrame,
    years: float,
    n_sims: int = _N_SIMS_DEFAULT,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Bootstrap test: is the measured edge driven by a handful of outlier trades?

    Method
    ------
    1. Compute per-trade percentage return: pnl / (entry_price × qty).
       This normalises for position size so each trade is comparable.
    2. Draw n_sims bootstrap samples with replacement (same n as original).
    3. For each sample compute annualised trade-level Sharpe, scaled by
       sqrt(trades_per_year) where trades_per_year = n_trades / years.
    4. Report the empirical distribution and the one-sided p-value:
       P(bootstrap Sharpe ≤ 0) — fraction of resamples that flip to negative.

    A low p-value (< 5%) means the edge survives resampling: even if we drew
    a different set of trades from the same distribution, we'd still expect a
    positive Sharpe.  A high p-value means a few big wins drive the result.

    Note: bootstrapping with replacement changes the sample mean and std (unlike
    permutation without replacement, where Sharpe is invariant to ordering).
    This is the standard non-parametric approach for Sharpe confidence intervals.

    Parameters
    ----------
    trades : closed-trade DataFrame from Engine.run()
    years  : backtest length in years (used to annualise trade-level Sharpe)
    n_sims : bootstrap replications (default 1000)
    seed   : random seed for reproducibility

    Returns
    -------
    dict with keys:
        actual_sharpe            — Sharpe of the real trade sequence
        sim_p5, sim_p25, sim_p50, sim_p75, sim_p95 — bootstrap distribution
        p_value                  — P(bootstrap Sharpe ≤ 0)
        n_trades, n_sims
    All values are None when fewer than 2 trades are available.
    """
    _empty: dict[str, Any] = {
        "actual_sharpe": None,
        "sim_p5":  None, "sim_p25": None, "sim_p50": None,
        "sim_p75": None, "sim_p95": None,
        "p_value":  None,
        "n_trades": len(trades) if not trades.empty else 0,
        "n_sims":   n_sims,
    }

    if trades.empty or len(trades) < 2:
        return _empty

    trade_returns = (
        trades["pnl"] / (trades["entry_price"] * trades["qty"])
    ).to_numpy(dtype=float)

    n_trades = len(trade_returns)
    trades_per_year = n_trades / years if years > 0 else float(n_trades)
    ann = float(np.sqrt(trades_per_year))

    actual_sharpe = _trade_sharpe(trade_returns, ann)

    rng = np.random.default_rng(seed)
    sim_sharpes = np.array([
        _trade_sharpe(rng.choice(trade_returns, size=n_trades, replace=True), ann)
        for _ in range(n_sims)
    ])

    return {
        "actual_sharpe": round(float(actual_sharpe), 4),
        "sim_p5":  round(float(np.percentile(sim_sharpes,  5)), 4),
        "sim_p25": round(float(np.percentile(sim_sharpes, 25)), 4),
        "sim_p50": round(float(np.percentile(sim_sharpes, 50)), 4),
        "sim_p75": round(float(np.percentile(sim_sharpes, 75)), 4),
        "sim_p95": round(float(np.percentile(sim_sharpes, 95)), 4),
        "p_value":  round(float(np.mean(sim_sharpes <= 0)), 4),
        "n_trades": n_trades,
        "n_sims":   n_sims,
    }
