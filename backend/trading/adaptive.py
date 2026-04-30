from __future__ import annotations

import os
import json
import logging
from typing import Any

from backend.utils.helpers import clamp

logger = logging.getLogger(__name__)

STATE_FILE = "adaptive_state.json"


class AdaptiveLearner:
    def __init__(self):
        self.source_reliability: dict[str, float] = {"finviz": 1.0, "yfinance": 1.0, "reddit": 0.8, "stocktwits": 0.8}
        self.vader_threshold = 0.35
        self.momentum_window = 180
        self.sizing_multiplier = 1.0
        self.win_count = 0
        self.loss_count = 0
        self.streak = 0
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                self.source_reliability = state.get("source_reliability", self.source_reliability)
                self.vader_threshold = state.get("vader_threshold", self.vader_threshold)
                self.momentum_window = state.get("momentum_window", self.momentum_window)
                self.sizing_multiplier = state.get("sizing_multiplier", self.sizing_multiplier)
                self.win_count = state.get("win_count", 0)
                self.loss_count = state.get("loss_count", 0)
                self.streak = state.get("streak", 0)
        except Exception as e:
            logger.warning(f"Failed to load adaptive state: {e}")

    def save_state(self):
        try:
            state = {
                "source_reliability": self.source_reliability,
                "vader_threshold": self.vader_threshold,
                "momentum_window": self.momentum_window,
                "sizing_multiplier": self.sizing_multiplier,
                "win_count": self.win_count,
                "loss_count": self.loss_count,
                "streak": self.streak,
            }
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save adaptive state: {e}")

    def record_outcome(self, source: str, profitable: bool):
        if profitable:
            self.win_count += 1
            self.streak = max(0, self.streak) + 1
            if source in self.source_reliability:
                self.source_reliability[source] = clamp(self.source_reliability[source] + 0.02, 0.3, 1.5)
            self.sizing_multiplier = clamp(self.sizing_multiplier + 0.03, 0.5, 1.5)
        else:
            self.loss_count += 1
            self.streak = min(0, self.streak) - 1
            if source in self.source_reliability:
                self.source_reliability[source] = clamp(self.source_reliability[source] - 0.03, 0.3, 1.5)
            self.sizing_multiplier = clamp(self.sizing_multiplier - 0.05, 0.5, 1.5)

        # Streak protection
        if self.streak <= -3:
            self.sizing_multiplier = clamp(self.sizing_multiplier * 0.75, 0.5, 1.5)
        if self.streak <= -6:
            self._revert_to_defaults()

        # Check overall win rate
        total = self.win_count + self.loss_count
        if total > 20 and self.win_count / total < 0.25:
            self._revert_to_defaults()

        self.save_state()

    def _revert_to_defaults(self):
        logger.warning("Adaptive learner reverting to defaults due to poor performance")
        self.source_reliability = {"finviz": 1.0, "yfinance": 1.0, "reddit": 0.8, "stocktwits": 0.8}
        self.vader_threshold = 0.35
        self.momentum_window = 180
        self.sizing_multiplier = 1.0
        self.streak = 0

    def get_adjusted_threshold(self) -> float:
        return clamp(self.vader_threshold, 0.2, 0.5)

    def get_source_weight(self, source: str) -> float:
        return self.source_reliability.get(source, 0.5)

    def get_sizing_multiplier(self) -> float:
        return self.sizing_multiplier

    def get_stats(self) -> dict[str, Any]:
        total = self.win_count + self.loss_count
        return {
            "winCount": self.win_count,
            "lossCount": self.loss_count,
            "winRate": round(self.win_count / total * 100, 1) if total > 0 else 0,
            "streak": self.streak,
            "sizingMultiplier": round(self.sizing_multiplier, 3),
            "vaderThreshold": round(self.vader_threshold, 3),
            "sourceReliability": {k: round(v, 3) for k, v in self.source_reliability.items()},
        }
