from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from backend.services.technical import compute_ema, compute_rsi
from backend.utils.helpers import safe_float

logger = logging.getLogger(__name__)


def momentum_signals(universe_data: dict[str, pd.DataFrame]) -> list[dict]:
    signals = []
    returns_12m = {}
    returns_1m = {}

    for ticker, df in universe_data.items():
        try:
            close = df["Close"]
            if len(close) < 60:
                continue
            ret_12m = (close.iloc[-1] / close.iloc[-min(252, len(close))] - 1) if len(close) > 20 else 0
            ret_1m = (close.iloc[-1] / close.iloc[-min(21, len(close))] - 1)
            # 12-1 momentum (skip most recent month)
            returns_12m[ticker] = ret_12m - ret_1m
            returns_1m[ticker] = ret_1m
        except Exception:
            continue

    if not returns_12m:
        return []

    # Cross-sectional ranking
    sorted_tickers = sorted(returns_12m.keys(), key=lambda t: returns_12m[t], reverse=True)
    n = len(sorted_tickers)
    top_quintile = set(sorted_tickers[:max(1, n // 5)])
    bottom_quintile = set(sorted_tickers[-max(1, n // 5):])

    for ticker, df in universe_data.items():
        try:
            close = df["Close"]
            ema_12 = compute_ema(close, 12)
            ema_26 = compute_ema(close, 26)
            rsi = compute_rsi(close, 14)
            current = safe_float(close.iloc[-1])
            ema12_val = safe_float(ema_12.iloc[-1])
            ema26_val = safe_float(ema_26.iloc[-1])
            rsi_val = safe_float(rsi.iloc[-1])

            score = 0
            # Cross-sectional
            if ticker in top_quintile:
                score += 0.4
            elif ticker in bottom_quintile:
                score -= 0.4
            # Time-series: positive 12m return
            if returns_12m.get(ticker, 0) > 0:
                score += 0.2
            else:
                score -= 0.2
            # EMA crossover
            if ema12_val > ema26_val:
                score += 0.2
            else:
                score -= 0.2
            # RSI
            if rsi_val < 30:
                score += 0.1
            elif rsi_val > 70:
                score -= 0.1

            if abs(score) > 0.2:
                signals.append({
                    "ticker": ticker,
                    "strategy": "momentum",
                    "score": round(score, 4),
                    "direction": "buy" if score > 0 else "sell",
                    "metrics": {
                        "return_12m": round(returns_12m.get(ticker, 0) * 100, 2),
                        "return_1m": round(returns_1m.get(ticker, 0) * 100, 2),
                        "rsi": round(rsi_val, 2),
                        "ema_cross": "bullish" if ema12_val > ema26_val else "bearish",
                    },
                })
        except Exception:
            continue

    return signals
