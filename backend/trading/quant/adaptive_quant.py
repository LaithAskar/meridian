from __future__ import annotations

import os
import json
import logging
from typing import Any

from backend.utils.helpers import clamp

logger = logging.getLogger(__name__)

QUANT_STATE_FILE = "adaptive_quant_state.json"


class AdaptiveQuant:
    def __init__(self):
        self.strategy_weights = {"momentum": 0.35, "mean_reversion": 0.30, "factor": 0.35}
        self.trade_threshold = 0.55
        self.sizing_multiplier = 1.0
        self.win_count = 0
        self.loss_count = 0
        self.streak = 0
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(QUANT_STATE_FILE):
                with open(QUANT_STATE_FILE, "r") as f:
                    state = json.load(f)
                self.strategy_weights = state.get("strategy_weights", self.strategy_weights)
                self.trade_threshold = state.get("trade_threshold", 0.55)
                self.sizing_multiplier = state.get("sizing_multiplier", 1.0)
                self.win_count = state.get("win_count", 0)
                self.loss_count = state.get("loss_count", 0)
                self.streak = state.get("streak", 0)
        except Exception as e:
            logger.warning(f"Failed to load quant adaptive state: {e}")

    def save_state(self):
        try:
            with open(QUANT_STATE_FILE, "w") as f:
                json.dump({
                    "strategy_weights": self.strategy_weights,
                    "trade_threshold": self.trade_threshold,
                    "sizing_multiplier": self.sizing_multiplier,
                    "win_count": self.win_count,
                    "loss_count": self.loss_count,
                    "streak": self.streak,
                }, f, indent=2)
        except Exception:
            pass

    def record_outcome(self, strategy: str, profitable: bool):
        if profitable:
            self.win_count += 1
            self.streak = max(0, self.streak) + 1
            if strategy in self.strategy_weights:
                self.strategy_weights[strategy] = clamp(self.strategy_weights[strategy] + 0.02, 0.1, 0.6)
            self.sizing_multiplier = clamp(self.sizing_multiplier + 0.02, 0.5, 1.5)
        else:
            self.loss_count += 1
            self.streak = min(0, self.streak) - 1
            if strategy in self.strategy_weights:
                self.strategy_weights[strategy] = clamp(self.strategy_weights[strategy] - 0.03, 0.1, 0.6)
            self.sizing_multiplier = clamp(self.sizing_multiplier - 0.04, 0.5, 1.5)

        # Normalize weights
        total = sum(self.strategy_weights.values())
        if total > 0:
            self.strategy_weights = {k: v / total for k, v in self.strategy_weights.items()}

        if self.streak <= -3:
            self.sizing_multiplier = clamp(self.sizing_multiplier * 0.7, 0.5, 1.5)
        if self.streak <= -7:
            self._revert()

        total_trades = self.win_count + self.loss_count
        if total_trades > 20 and self.win_count / total_trades < 0.30:
            self._revert()

        self.save_state()

    def _revert(self):
        self.strategy_weights = {"momentum": 0.35, "mean_reversion": 0.30, "factor": 0.35}
        self.trade_threshold = 0.55
        self.sizing_multiplier = 1.0
        self.streak = 0

    def get_weights(self) -> dict[str, float]:
        return dict(self.strategy_weights)

    def get_stats(self) -> dict[str, Any]:
        total = self.win_count + self.loss_count
        return {
            "winCount": self.win_count,
            "lossCount": self.loss_count,
            "winRate": round(self.win_count / total * 100, 1) if total > 0 else 0,
            "streak": self.streak,
            "sizingMultiplier": round(self.sizing_multiplier, 3),
            "strategyWeights": {k: round(v, 3) for k, v in self.strategy_weights.items()},
        }
