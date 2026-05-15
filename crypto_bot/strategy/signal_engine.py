from __future__ import annotations

import os
import json
import logging
from typing import Any

from crypto_bot.indicators.composite import compute_composite_score
from crypto_bot.indicators.technical import adx as compute_adx, ema
from crypto_bot.indicators.statistical import hurst_exponent

logger = logging.getLogger(__name__)

CRYPTO_ADAPTIVE_FILE = "crypto_adaptive_state.json"


class RegimeDetector:
    def detect(self, df) -> str:
        if df is None or df.empty or len(df) < 30:
            return "neutral"
        try:
            close = df["close"]
            adx_val = float(compute_adx(df["high"], df["low"], close).iloc[-1])
            h = hurst_exponent(close)
            e12 = float(ema(close, 12).iloc[-1])
            e26 = float(ema(close, 26).iloc[-1])
            if adx_val > 30 and h > 0.55:
                return "trending"
            if h < 0.45 and adx_val < 20:
                return "mean_reverting"
            if adx_val < 15:
                return "choppy"
            return "neutral"
        except Exception:
            return "neutral"


class CryptoAdaptive:
    def __init__(self):
        self.indicator_weights = {
            "rsi": 0.15, "macd": 0.15, "bb": 0.12, "trend": 0.15,
            "volume": 0.10, "stoch": 0.10, "adx": 0.08, "zscore": 0.08, "hurst": 0.07,
        }
        self.regime_multipliers = {"trending": 1.2, "mean_reverting": 0.8, "choppy": 0.5, "neutral": 1.0}
        self.atr_stop_mult = 1.8
        self.win_count = 0
        self.loss_count = 0
        self.streak = 0
        self._load()

    def _load(self):
        try:
            if os.path.exists(CRYPTO_ADAPTIVE_FILE):
                with open(CRYPTO_ADAPTIVE_FILE) as f:
                    s = json.load(f)
                self.indicator_weights = s.get("indicator_weights", self.indicator_weights)
                self.regime_multipliers = s.get("regime_multipliers", self.regime_multipliers)
                self.atr_stop_mult = s.get("atr_stop_mult", 1.8)
                self.win_count = s.get("win_count", 0)
                self.loss_count = s.get("loss_count", 0)
                self.streak = s.get("streak", 0)
        except Exception:
            pass

    def save(self):
        try:
            with open(CRYPTO_ADAPTIVE_FILE, "w") as f:
                json.dump({
                    "indicator_weights": self.indicator_weights,
                    "regime_multipliers": self.regime_multipliers,
                    "atr_stop_mult": self.atr_stop_mult,
                    "win_count": self.win_count,
                    "loss_count": self.loss_count,
                    "streak": self.streak,
                }, f, indent=2)
        except Exception:
            pass

    def record(self, profitable: bool):
        if profitable:
            self.win_count += 1
            self.streak = max(0, self.streak) + 1
        else:
            self.loss_count += 1
            self.streak = min(0, self.streak) - 1
        if self.streak <= -3:
            self.atr_stop_mult = min(2.5, self.atr_stop_mult + 0.1)
        if self.streak <= -6:
            self._revert()
        self.save()

    def _revert(self):
        self.indicator_weights = {
            "rsi": 0.15, "macd": 0.15, "bb": 0.12, "trend": 0.15,
            "volume": 0.10, "stoch": 0.10, "adx": 0.08, "zscore": 0.08, "hurst": 0.07,
        }
        self.atr_stop_mult = 1.8
        self.streak = 0


class SignalEngine:
    def __init__(self, config: dict):
        self.buy_threshold = config.get("buy_threshold", 0.25)
        self.sell_threshold = config.get("sell_threshold", -0.20)
        self.min_confirmations = config.get("min_confirmations", 3)
        self.regime_detector = RegimeDetector()
        self.adaptive = CryptoAdaptive()

    def evaluate(self, symbol: str, df) -> dict[str, Any]:
        if df is None or df.empty:
            return {"action": "HOLD", "symbol": symbol, "score": 0}
        regime = self.regime_detector.detect(df)
        regime_mult = self.adaptive.regime_multipliers.get(regime, 1.0)
        comp = compute_composite_score(df, self.adaptive.indicator_weights)
        adjusted_score = comp["score"] / 100 * regime_mult

        action = "HOLD"
        if adjusted_score >= self.buy_threshold and comp["buyConfirms"] >= self.min_confirmations:
            action = "BUY"
        elif adjusted_score <= self.sell_threshold and comp["sellConfirms"] >= self.min_confirmations:
            action = "SELL"

        return {
            "action": action,
            "symbol": symbol,
            "score": round(adjusted_score, 4),
            "rawScore": comp["score"],
            "regime": regime,
            "confirmations": comp["confirmations"],
            "buyConfirms": comp["buyConfirms"],
            "sellConfirms": comp["sellConfirms"],
            "metrics": comp.get("metrics", {}),
            "signals": comp.get("signals", {}),
        }
