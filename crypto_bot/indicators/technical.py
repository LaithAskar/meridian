from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ef = series.ewm(span=fast, adjust=False).mean()
    es = series.ewm(span=slow, adjust=False).mean()
    m = ef - es
    s = m.ewm(span=signal, adjust=False).mean()
    h = m - s
    return m, s, h


def bollinger_bands(series: pd.Series, period: int = 20, std: float = 2.0):
    sma = series.rolling(window=period, min_periods=1).mean()
    sd = series.rolling(window=period, min_periods=1).std()
    return sma + std * sd, sma, sma - std * sd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    tp = (high + low + close) / 3
    return (tp * volume).cumsum() / volume.cumsum().replace(0, np.nan)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    d = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (volume * d).cumsum()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    r = rsi(series, rsi_period)
    rmin = r.rolling(window=stoch_period, min_periods=1).min()
    rmax = r.rolling(window=stoch_period, min_periods=1).max()
    return ((r - rmin) / (rmax - rmin).replace(0, np.nan) * 100).fillna(50)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    pdm = high.diff()
    mdm = -low.diff()
    pdm = pdm.where((pdm > mdm) & (pdm > 0), 0.0)
    mdm = mdm.where((mdm > pdm) & (mdm > 0), 0.0)
    a = atr(high, low, close, period)
    pdi = 100 * pdm.ewm(span=period, adjust=False).mean() / a.replace(0, np.nan)
    mdi = 100 * mdm.ewm(span=period, adjust=False).mean() / a.replace(0, np.nan)
    dx = 100 * abs(pdi - mdi) / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean().fillna(0)
