from __future__ import annotations

import numpy as np
import pandas as pd


def z_score(series: pd.Series, period: int = 20) -> pd.Series:
    mean = series.rolling(window=period, min_periods=1).mean()
    std = series.rolling(window=period, min_periods=1).std().replace(0, np.nan)
    return ((series - mean) / std).fillna(0)


def hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    try:
        lags = range(2, min(max_lag, len(series) // 2))
        tau = [np.std(np.subtract(series[lag:].values, series[:-lag].values)) for lag in lags]
        tau = [t for t in tau if t > 0]
        if len(tau) < 3:
            return 0.5
        reg = np.polyfit(np.log(list(range(2, 2 + len(tau)))), np.log(tau), 1)
        return float(reg[0])
    except Exception:
        return 0.5


def autocorrelation(series: pd.Series, lag: int = 1) -> float:
    try:
        return float(series.autocorr(lag=lag))
    except Exception:
        return 0


def rolling_sharpe(returns: pd.Series, period: int = 30, risk_free: float = 0) -> pd.Series:
    mean = returns.rolling(window=period, min_periods=1).mean()
    std = returns.rolling(window=period, min_periods=1).std().replace(0, np.nan)
    return ((mean - risk_free / 252) / std * np.sqrt(252)).fillna(0)


def volatility_percentile(series: pd.Series, period: int = 30, lookback: int = 252) -> float:
    try:
        returns = series.pct_change().dropna()
        current_vol = returns.tail(period).std() * np.sqrt(252)
        hist_vols = returns.rolling(window=period).std().dropna() * np.sqrt(252)
        if len(hist_vols) < 10:
            return 50
        pct = (hist_vols < current_vol).mean() * 100
        return float(pct)
    except Exception:
        return 50
