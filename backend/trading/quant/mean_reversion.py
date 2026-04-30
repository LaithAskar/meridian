from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from backend.services.technical import compute_rsi, compute_bollinger, compute_sma
from backend.utils.helpers import safe_float

logger = logging.getLogger(__name__)


def mean_reversion_signals(universe_data: dict[str, pd.DataFrame]) -> list[dict]:
    signals = []
    for ticker, df in universe_data.items():
        try:
            close = df["Close"]
            if len(close) < 30:
                continue
            current = safe_float(close.iloc[-1])
            rsi = compute_rsi(close, 14)
            rsi_val = safe_float(rsi.iloc[-1])
            bb = compute_bollinger(close, 20, 2.0)
            bb_upper = safe_float(bb["upper"].iloc[-1])
            bb_lower = safe_float(bb["lower"].iloc[-1])
            bb_mid = safe_float(bb["middle"].iloc[-1])
            sma_20 = safe_float(compute_sma(close, 20).iloc[-1])
            z_score = (current - sma_20) / (close.rolling(20).std().iloc[-1] or 1)

            score = 0
            # RSI extremes
            if rsi_val < 25:
                score += 0.35
            elif rsi_val < 35:
                score += 0.15
            elif rsi_val > 75:
                score -= 0.35
            elif rsi_val > 65:
                score -= 0.15

            # Bollinger position
            if current <= bb_lower:
                score += 0.3
            elif current >= bb_upper:
                score -= 0.3
            elif current < bb_mid:
                score += 0.1
            else:
                score -= 0.1

            # Z-score
            if z_score < -2:
                score += 0.25
            elif z_score < -1:
                score += 0.1
            elif z_score > 2:
                score -= 0.25
            elif z_score > 1:
                score -= 0.1

            if abs(score) > 0.2:
                signals.append({
                    "ticker": ticker,
                    "strategy": "mean_reversion",
                    "score": round(score, 4),
                    "direction": "buy" if score > 0 else "sell",
                    "metrics": {
                        "rsi": round(rsi_val, 2),
                        "z_score": round(float(z_score), 2),
                        "bb_position": round((current - bb_lower) / max(bb_upper - bb_lower, 0.01), 3),
                    },
                })
        except Exception:
            continue
    return signals
