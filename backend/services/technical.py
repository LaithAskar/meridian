from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backend.utils.helpers import TTLCache, safe_float, safe_div

logger = logging.getLogger(__name__)


def compute_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=1).mean()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def compute_bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    sma = compute_sma(series, period)
    std = series.rolling(window=period, min_periods=1).std()
    return {"upper": sma + std_dev * std, "middle": sma, "lower": sma - std_dev * std}


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr = compute_atr(high, low, close, period)
    plus_di = 100 * compute_ema(plus_dm, period) / atr.replace(0, np.nan)
    minus_di = 100 * compute_ema(minus_dm, period) / atr.replace(0, np.nan)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    adx = compute_ema(dx.fillna(0), period)
    return adx.fillna(0)


def compute_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    tp = (high + low + close) / 3
    cum_tpv = (tp * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tpv / cum_vol.replace(0, np.nan)


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (volume * direction).cumsum()


def compute_stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    rsi = compute_rsi(series, rsi_period)
    rsi_min = rsi.rolling(window=stoch_period, min_periods=1).min()
    rsi_max = rsi.rolling(window=stoch_period, min_periods=1).max()
    stoch = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    return (stoch * 100).fillna(50)


@TTLCache(ttl=120, maxsize=100)
def get_technical_analysis(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        df = t.history(period="6mo", interval="1d")
        if df is None or df.empty or len(df) < 20:
            return {"score": 0, "breakdown": {}, "indicators": {}}

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        current = safe_float(close.iloc[-1])

        sma_20 = compute_sma(close, 20)
        sma_50 = compute_sma(close, 50)
        sma_200 = compute_sma(close, 200)
        ema_12 = compute_ema(close, 12)
        ema_26 = compute_ema(close, 26)

        rsi_val = safe_float(compute_rsi(close).iloc[-1])
        macd_data = compute_macd(close)
        macd_val = safe_float(macd_data["macd"].iloc[-1])
        macd_sig = safe_float(macd_data["signal"].iloc[-1])
        macd_hist = safe_float(macd_data["histogram"].iloc[-1])

        bb = compute_bollinger(close)
        bb_upper = safe_float(bb["upper"].iloc[-1])
        bb_lower = safe_float(bb["lower"].iloc[-1])
        bb_mid = safe_float(bb["middle"].iloc[-1])

        atr_val = safe_float(compute_atr(high, low, close).iloc[-1])
        adx_val = safe_float(compute_adx(high, low, close).iloc[-1])

        stoch_rsi = safe_float(compute_stoch_rsi(close).iloc[-1])

        sma_20_val = safe_float(sma_20.iloc[-1])
        sma_50_val = safe_float(sma_50.iloc[-1])
        sma_200_val = safe_float(sma_200.iloc[-1]) if len(df) >= 200 else 0

        # Score calculation (-100 to +100)
        score = 0
        ma_signals = 0
        ma_total = 0

        for sma_val, label in [(sma_20_val, "SMA20"), (sma_50_val, "SMA50"), (sma_200_val, "SMA200")]:
            if sma_val > 0:
                ma_total += 1
                if current > sma_val:
                    score += 10
                    ma_signals += 1
                else:
                    score -= 10

        # RSI
        if rsi_val < 30:
            score += 15  # oversold = bullish
        elif rsi_val > 70:
            score -= 15  # overbought = bearish
        elif rsi_val < 50:
            score -= 5
        else:
            score += 5

        # MACD
        if macd_hist > 0:
            score += 15
        else:
            score -= 15

        # Bollinger
        bb_range = bb_upper - bb_lower if bb_upper > bb_lower else 1
        bb_position = (current - bb_lower) / bb_range
        if bb_position < 0.2:
            score += 10
        elif bb_position > 0.8:
            score -= 10

        # ADX trend strength
        if adx_val > 25:
            score = int(score * 1.2)

        score = max(-100, min(100, score))

        ma_signal = "buy" if ma_signals > ma_total / 2 else "sell" if ma_signals < ma_total / 2 else "neutral"
        momentum_signal = "buy" if rsi_val < 40 and macd_hist > 0 else "sell" if rsi_val > 60 and macd_hist < 0 else "neutral"

        return {
            "score": score,
            "breakdown": {
                "movingAverages": {"signal": ma_signal, "count": ma_signals, "total": ma_total},
                "momentum": {"signal": momentum_signal, "rsi": round(rsi_val, 2), "macdHistogram": round(macd_hist, 4)},
                "volatility": {"atr": round(atr_val, 2), "adx": round(adx_val, 2), "bbWidth": round(bb_range, 2)},
                "trend": {"signal": "bullish" if score > 20 else "bearish" if score < -20 else "neutral", "strength": round(adx_val, 1)},
            },
            "indicators": {
                "sma20": round(sma_20_val, 2),
                "sma50": round(sma_50_val, 2),
                "sma200": round(sma_200_val, 2),
                "ema12": round(safe_float(ema_12.iloc[-1]), 2),
                "ema26": round(safe_float(ema_26.iloc[-1]), 2),
                "rsi": round(rsi_val, 2),
                "macd": round(macd_val, 4),
                "macdSignal": round(macd_sig, 4),
                "macdHistogram": round(macd_hist, 4),
                "bollingerUpper": round(bb_upper, 2),
                "bollingerMiddle": round(bb_mid, 2),
                "bollingerLower": round(bb_lower, 2),
                "atr": round(atr_val, 2),
                "adx": round(adx_val, 2),
                "stochRsi": round(stoch_rsi, 2),
                "currentPrice": round(current, 2),
            },
        }
    except Exception as e:
        logger.error(f"Technical analysis error for {ticker}: {e}")
        return {"score": 0, "breakdown": {}, "indicators": {}}
