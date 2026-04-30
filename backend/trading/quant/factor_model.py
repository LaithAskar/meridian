from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from backend.trading.quant.data_engine import get_fundamentals
from backend.utils.helpers import safe_float, safe_div

logger = logging.getLogger(__name__)


def factor_signals(universe_data: dict[str, pd.DataFrame]) -> list[dict]:
    signals = []
    tickers = list(universe_data.keys())
    fundamentals = {}
    for t in tickers:
        fundamentals[t] = get_fundamentals(t)

    # Compute factor scores
    scores = {}
    for t in tickers:
        f = fundamentals[t]
        close = universe_data[t]["Close"]
        vol = close.pct_change().rolling(60).std().iloc[-1] if len(close) > 60 else 0.02

        # Value: low PE, low PB
        value_score = 0
        pe = f["pe"]
        pb = f["pb"]
        if 0 < pe < 15:
            value_score += 0.3
        elif 0 < pe < 25:
            value_score += 0.1
        if 0 < pb < 3:
            value_score += 0.2
        elif 0 < pb < 5:
            value_score += 0.1

        # Quality: high ROE, high margins
        quality_score = 0
        if f["roe"] > 20:
            quality_score += 0.3
        elif f["roe"] > 10:
            quality_score += 0.15
        if f["margin"] > 20:
            quality_score += 0.2
        elif f["margin"] > 10:
            quality_score += 0.1

        # Momentum: 6-month return
        mom_score = 0
        if len(close) >= 126:
            ret_6m = (close.iloc[-1] / close.iloc[-126] - 1)
            if ret_6m > 0.15:
                mom_score = 0.3
            elif ret_6m > 0.05:
                mom_score = 0.15
            elif ret_6m < -0.1:
                mom_score = -0.2
        else:
            ret_6m = 0

        # Low volatility
        low_vol_score = 0
        if float(vol) < 0.015:
            low_vol_score = 0.2
        elif float(vol) < 0.025:
            low_vol_score = 0.1
        elif float(vol) > 0.04:
            low_vol_score = -0.1

        composite = value_score * 0.25 + quality_score * 0.25 + mom_score * 0.3 + low_vol_score * 0.2
        scores[t] = {
            "composite": composite,
            "value": value_score,
            "quality": quality_score,
            "momentum": mom_score,
            "lowVol": low_vol_score,
            "volatility": round(float(vol) * 100, 2),
        }

    for t, s in scores.items():
        if abs(s["composite"]) > 0.1:
            signals.append({
                "ticker": t,
                "strategy": "factor_model",
                "score": round(s["composite"], 4),
                "direction": "buy" if s["composite"] > 0 else "sell",
                "metrics": s,
            })

    return signals
