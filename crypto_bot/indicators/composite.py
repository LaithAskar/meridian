from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from crypto_bot.indicators.technical import rsi, macd, bollinger_bands, atr, obv, ema, stoch_rsi, adx
from crypto_bot.indicators.statistical import z_score, hurst_exponent, volatility_percentile

logger = logging.getLogger(__name__)


def compute_composite_score(df: pd.DataFrame, weights: dict[str, float] | None = None) -> dict:
    if df is None or df.empty or len(df) < 20:
        return {"score": 0, "signals": {}, "confirmations": 0}

    w = weights or {
        "rsi": 0.15, "macd": 0.15, "bb": 0.12, "trend": 0.15,
        "volume": 0.10, "stoch": 0.10, "adx": 0.08, "zscore": 0.08, "hurst": 0.07,
    }

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    signals = {}
    scores = {}

    # RSI
    rsi_val = float(rsi(close).iloc[-1])
    if rsi_val < 30:
        scores["rsi"] = 0.8
        signals["rsi"] = "oversold"
    elif rsi_val < 40:
        scores["rsi"] = 0.3
        signals["rsi"] = "slightly_oversold"
    elif rsi_val > 70:
        scores["rsi"] = -0.8
        signals["rsi"] = "overbought"
    elif rsi_val > 60:
        scores["rsi"] = -0.3
        signals["rsi"] = "slightly_overbought"
    else:
        scores["rsi"] = 0
        signals["rsi"] = "neutral"

    # MACD
    m, s, h = macd(close)
    macd_hist = float(h.iloc[-1])
    prev_hist = float(h.iloc[-2]) if len(h) > 1 else 0
    if macd_hist > 0 and macd_hist > prev_hist:
        scores["macd"] = 0.8
        signals["macd"] = "bullish_momentum"
    elif macd_hist > 0:
        scores["macd"] = 0.3
        signals["macd"] = "bullish"
    elif macd_hist < 0 and macd_hist < prev_hist:
        scores["macd"] = -0.8
        signals["macd"] = "bearish_momentum"
    elif macd_hist < 0:
        scores["macd"] = -0.3
        signals["macd"] = "bearish"
    else:
        scores["macd"] = 0
        signals["macd"] = "neutral"

    # Bollinger Bands
    upper, mid, lower = bollinger_bands(close)
    current = float(close.iloc[-1])
    bb_range = float(upper.iloc[-1]) - float(lower.iloc[-1])
    if bb_range > 0:
        bb_pos = (current - float(lower.iloc[-1])) / bb_range
    else:
        bb_pos = 0.5
    if bb_pos < 0.15:
        scores["bb"] = 0.7
        signals["bb"] = "below_lower"
    elif bb_pos > 0.85:
        scores["bb"] = -0.7
        signals["bb"] = "above_upper"
    else:
        scores["bb"] = (0.5 - bb_pos) * 0.5
        signals["bb"] = "within_bands"

    # Trend (EMA cross)
    ema12 = float(ema(close, 12).iloc[-1])
    ema26 = float(ema(close, 26).iloc[-1])
    if ema12 > ema26:
        scores["trend"] = 0.6
        signals["trend"] = "bullish"
    else:
        scores["trend"] = -0.6
        signals["trend"] = "bearish"

    # Volume
    vol_avg = float(volume.rolling(20).mean().iloc[-1]) if len(volume) > 20 else float(volume.mean())
    vol_ratio = float(volume.iloc[-1]) / vol_avg if vol_avg > 0 else 1
    if vol_ratio > 2:
        scores["volume"] = 0.5 if scores.get("trend", 0) > 0 else -0.5
        signals["volume"] = "high_volume"
    else:
        scores["volume"] = 0
        signals["volume"] = "normal"

    # Stochastic RSI
    sr = float(stoch_rsi(close).iloc[-1])
    if sr < 20:
        scores["stoch"] = 0.6
        signals["stoch"] = "oversold"
    elif sr > 80:
        scores["stoch"] = -0.6
        signals["stoch"] = "overbought"
    else:
        scores["stoch"] = 0
        signals["stoch"] = "neutral"

    # ADX
    adx_val = float(adx(high, low, close).iloc[-1])
    if adx_val > 25:
        scores["adx"] = 0.3
        signals["adx"] = "strong_trend"
    else:
        scores["adx"] = -0.1
        signals["adx"] = "weak_trend"

    # Z-score
    zs = float(z_score(close, 20).iloc[-1])
    if zs < -2:
        scores["zscore"] = 0.7
        signals["zscore"] = "extremely_low"
    elif zs > 2:
        scores["zscore"] = -0.7
        signals["zscore"] = "extremely_high"
    else:
        scores["zscore"] = -zs * 0.2
        signals["zscore"] = "normal"

    # Hurst
    h_val = hurst_exponent(close)
    if h_val > 0.55:
        scores["hurst"] = 0.3
        signals["hurst"] = "trending"
    elif h_val < 0.45:
        scores["hurst"] = -0.1
        signals["hurst"] = "mean_reverting"
    else:
        scores["hurst"] = 0
        signals["hurst"] = "random"

    # Weighted composite
    total = sum(w.get(k, 0) * scores.get(k, 0) for k in w)
    total = max(-1, min(1, total)) * 100

    # Count confirmations
    buy_confirms = sum(1 for v in scores.values() if v > 0.2)
    sell_confirms = sum(1 for v in scores.values() if v < -0.2)
    confirmations = max(buy_confirms, sell_confirms)

    return {
        "score": round(total, 2),
        "signals": signals,
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "confirmations": confirmations,
        "buyConfirms": buy_confirms,
        "sellConfirms": sell_confirms,
        "metrics": {
            "rsi": round(rsi_val, 2),
            "macd_hist": round(macd_hist, 6),
            "bb_position": round(bb_pos, 3),
            "adx": round(adx_val, 2),
            "z_score": round(zs, 2),
            "hurst": round(h_val, 3),
            "stoch_rsi": round(sr, 2),
            "volume_ratio": round(vol_ratio, 2),
        },
    }
