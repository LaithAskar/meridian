"""
Performance metrics for the Meridian backtester.

All functions accept the data shapes produced by Engine.run():

  equity_curve : pd.DataFrame with columns ['equity', 'cash', 'num_positions'],
                 DatetimeIndex, one row per trading day.
  trades       : pd.DataFrame with columns ['symbol', 'entry_ts', 'exit_ts',
                 'qty', 'entry_price', 'exit_price', 'pnl', 'holding_days'].
  returns      : pd.Series of daily fractional returns (float).

Annualisation
-------------
Daily Sharpe uses sqrt(252) per DESIGN.md (yfinance daily bars).  The older
hourly factor sqrt(252 × 6.5) is not used here.

Sharpe standard error
---------------------
SE(SR) ≈ sqrt((1 + SR² / 2) / n), the Mertens / Lo (2002) approximation for
iid returns.  Report alongside the point estimate so regime-split comparisons
can show whether the gap between pre- and post-COVID Sharpes is statistically
meaningful.  For strategies with significant autocorrelation the true SE is
wider; this approximation is the standard quant-finance / interview convention.

Max drawdown sign convention
-----------------------------
max_drawdown() returns the magnitude as a positive float: 0.25 means a 25%
peak-to-trough decline.  This is cleaner in summary tables than a negative
value.  The underlying minimum drawdown (always ≤ 0) is just negated before
returning.
"""

from __future__ import annotations

import math

import pandas as pd

_TRADING_DAYS_PER_YEAR: int = 252


def sharpe(returns: pd.Series, freq: str = "daily") -> float:
    """
    Annualised Sharpe ratio.

    Parameters
    ----------
    returns : daily fractional returns, e.g. equity['equity'].pct_change().dropna()
    freq    : 'daily' only (placeholder for extensibility; raises if anything else)

    Returns
    -------
    float — annualised SR.  Returns 0.0 if std is zero (flat or empty returns).
    """
    if freq != "daily":
        raise ValueError(f"Unsupported freq {freq!r}; only 'daily' is supported")
    if returns.empty or len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    if std == 0.0:
        return 0.0
    return float(returns.mean() / std) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def sharpe_se(returns: pd.Series) -> float:
    """
    Standard error of the annualised Sharpe ratio estimate.

    Mertens / Lo (2002) iid approximation:
        SE(SR) ≈ sqrt((1 + SR² / 2) / n)

    Returns nan if fewer than 2 observations.
    """
    n = len(returns)
    if n < 2:
        return float("nan")
    sr = sharpe(returns)
    return math.sqrt((1.0 + sr ** 2 / 2.0) / n)


def max_drawdown(equity_curve: pd.Series | pd.DataFrame) -> float:
    """
    Maximum peak-to-trough drawdown as a positive fraction.

    E.g. 0.25 means the portfolio fell 25% from its running peak.

    Parameters
    ----------
    equity_curve : Series of equity values, or DataFrame with an 'equity' column.

    Returns
    -------
    float ≥ 0.  Returns 0.0 for a monotonically non-decreasing or flat curve.
    """
    eq: pd.Series = equity_curve["equity"] if isinstance(equity_curve, pd.DataFrame) else equity_curve

    if eq.empty or len(eq) < 2:
        return 0.0

    running_max = eq.cummax()
    drawdown = (eq - running_max) / running_max
    return float(-drawdown.min())  # min ≤ 0; negate → positive magnitude


def hit_rate(trades: pd.DataFrame) -> float:
    """
    Fraction of closed trades that were profitable (pnl > 0).

    Returns 0.0 if there are no trades.
    """
    if trades.empty:
        return 0.0
    return float((trades["pnl"] > 0).mean())


def avg_win_loss(trades: pd.DataFrame) -> dict[str, float]:
    """
    Average win, average loss, and win/loss ratio for a set of closed trades.

    Returns
    -------
    dict with keys:
      'avg_win'       — mean P&L of profitable trades (positive float, or nan if none)
      'avg_loss'      — mean P&L of losing trades     (negative float, or nan if none)
      'win_loss_ratio'— abs(avg_win / avg_loss)        (positive float, or nan)

    nan is returned for quantities that cannot be computed (no wins, no losses,
    or avg_loss == 0).
    """
    _nan = float("nan")
    if trades.empty:
        return {"avg_win": _nan, "avg_loss": _nan, "win_loss_ratio": _nan}

    wins   = trades.loc[trades["pnl"] > 0, "pnl"]
    losses = trades.loc[trades["pnl"] < 0, "pnl"]

    avg_win  = float(wins.mean())   if not wins.empty   else _nan
    avg_loss = float(losses.mean()) if not losses.empty else _nan

    if not (math.isnan(avg_win) or math.isnan(avg_loss)) and avg_loss != 0.0:
        win_loss_ratio = abs(avg_win / avg_loss)
    else:
        win_loss_ratio = _nan

    return {"avg_win": avg_win, "avg_loss": avg_loss, "win_loss_ratio": win_loss_ratio}


def exposure(equity_curve: pd.DataFrame) -> float:
    """
    Fraction of trading days with at least one open position.

    Uses the 'num_positions' column from the equity curve DataFrame.
    Returns 0.0 if the curve is empty.
    """
    if equity_curve.empty:
        return 0.0
    return float((equity_curve["num_positions"] > 0).mean())


def cagr(equity_curve: pd.Series | pd.DataFrame, years: float) -> float:
    """
    Compound annual growth rate.

    CAGR = (final / initial) ** (1 / years) − 1

    Parameters
    ----------
    equity_curve : Series of equity values, or DataFrame with an 'equity' column.
    years        : length of the backtest window in years (e.g. 14.0 for 2010-2024).

    Returns
    -------
    float — e.g. 0.12 = 12 % annualised growth.  Negative if equity declined.

    Raises
    ------
    ValueError if years ≤ 0 or if initial equity is zero.
    """
    if years <= 0:
        raise ValueError(f"years must be positive; got {years}")

    eq: pd.Series = equity_curve["equity"] if isinstance(equity_curve, pd.DataFrame) else equity_curve
    if eq.empty:
        return 0.0

    initial = float(eq.iloc[0])
    if initial == 0.0:
        raise ValueError("initial equity is zero — CAGR is undefined")

    return (float(eq.iloc[-1]) / initial) ** (1.0 / years) - 1.0


def total_return(equity_curve: pd.Series | pd.DataFrame) -> float:
    """
    Total return over the full backtest window: (final − initial) / initial.

    Raises ValueError if initial equity is zero or the curve is empty.
    """
    eq: pd.Series = equity_curve["equity"] if isinstance(equity_curve, pd.DataFrame) else equity_curve
    if eq.empty:
        raise ValueError("equity_curve is empty")

    initial = float(eq.iloc[0])
    if initial == 0.0:
        raise ValueError("initial equity is zero — total return is undefined")

    return (float(eq.iloc[-1]) - initial) / initial


def avg_holding_period(trades: pd.DataFrame) -> float:
    """
    Mean holding period in calendar days across all closed trades.

    Returns nan if there are no trades.
    """
    if trades.empty:
        return float("nan")
    return float(trades["holding_days"].mean())
