from __future__ import annotations

import logging
from typing import Any

import yfinance as yf
import pandas as pd

from backend.services.technical import compute_sma, compute_rsi
from backend.utils.helpers import TTLCache, safe_float

logger = logging.getLogger(__name__)


@TTLCache(ttl=300, maxsize=1)
def detect_regime() -> dict[str, Any]:
    try:
        # VIX
        vix = yf.Ticker("^VIX")
        vix_data = vix.history(period="1mo", interval="1d")
        vix_level = safe_float(vix_data["Close"].iloc[-1]) if len(vix_data) > 0 else 20

        # SPY trend
        spy = yf.Ticker("SPY")
        spy_data = spy.history(period="6mo", interval="1d")
        spy_close = spy_data["Close"] if len(spy_data) > 0 else pd.Series([0])
        spy_sma50 = safe_float(compute_sma(spy_close, 50).iloc[-1])
        spy_sma200 = safe_float(compute_sma(spy_close, 200).iloc[-1]) if len(spy_close) >= 200 else spy_sma50
        spy_current = safe_float(spy_close.iloc[-1])
        spy_rsi = safe_float(compute_rsi(spy_close, 14).iloc[-1])

        # Determine regime
        if vix_level > 30:
            regime = "crisis"
        elif vix_level > 22:
            regime = "high_volatility"
        elif spy_current > spy_sma50 > spy_sma200:
            regime = "bull_trend"
        elif spy_current < spy_sma50 < spy_sma200:
            regime = "bear_trend"
        else:
            regime = "neutral"

        # Strategy weight adjustments
        weights = {
            "crisis": {"momentum": 0.1, "mean_reversion": 0.6, "factor": 0.3},
            "high_volatility": {"momentum": 0.2, "mean_reversion": 0.5, "factor": 0.3},
            "bull_trend": {"momentum": 0.5, "mean_reversion": 0.2, "factor": 0.3},
            "bear_trend": {"momentum": 0.15, "mean_reversion": 0.45, "factor": 0.4},
            "neutral": {"momentum": 0.35, "mean_reversion": 0.30, "factor": 0.35},
        }

        return {
            "regime": regime,
            "vix": round(vix_level, 2),
            "spyCurrent": round(spy_current, 2),
            "spySma50": round(spy_sma50, 2),
            "spySma200": round(spy_sma200, 2),
            "spyRsi": round(spy_rsi, 2),
            "strategyWeights": weights.get(regime, weights["neutral"]),
        }
    except Exception as e:
        logger.error(f"Regime detection error: {e}")
        return {
            "regime": "neutral",
            "vix": 20,
            "strategyWeights": {"momentum": 0.35, "mean_reversion": 0.30, "factor": 0.35},
        }
