from __future__ import annotations

import time
import logging
from collections import defaultdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MomentumTracker:
    def __init__(self, window_seconds: int = 180, min_agreement: float = 0.6):
        self.window_seconds = window_seconds
        self.min_agreement = min_agreement
        self._signals: dict[str, list[tuple[float, str]]] = defaultdict(list)

    def add_signal(self, ticker: str, direction: str):
        now = time.time()
        self._signals[ticker].append((now, direction))
        cutoff = now - self.window_seconds
        self._signals[ticker] = [(t, d) for t, d in self._signals[ticker] if t > cutoff]

    def get_consensus(self, ticker: str) -> dict[str, Any]:
        now = time.time()
        cutoff = now - self.window_seconds
        signals = [(t, d) for t, d in self._signals.get(ticker, []) if t > cutoff]
        if not signals:
            return {"direction": "neutral", "strength": 0, "count": 0, "consensus": False}
        bullish = sum(1 for _, d in signals if d == "bullish")
        bearish = sum(1 for _, d in signals if d == "bearish")
        total = len(signals)
        if bullish > bearish and bullish / total >= self.min_agreement:
            return {"direction": "bullish", "strength": round(bullish / total, 3), "count": total, "consensus": True}
        elif bearish > bullish and bearish / total >= self.min_agreement:
            return {"direction": "bearish", "strength": round(bearish / total, 3), "count": total, "consensus": True}
        return {"direction": "neutral", "strength": 0, "count": total, "consensus": False}


class PositionTracker:
    def __init__(self):
        self._positions: dict[str, dict] = {}

    def update(self, ticker: str, side: str, dollars: float):
        if side == "buy":
            if ticker in self._positions:
                self._positions[ticker]["dollars"] += dollars
                self._positions[ticker]["trades"] += 1
            else:
                self._positions[ticker] = {"dollars": dollars, "trades": 1, "side": "long"}
        elif side == "sell":
            if ticker in self._positions:
                self._positions[ticker]["dollars"] -= dollars
                if self._positions[ticker]["dollars"] <= 0:
                    del self._positions[ticker]

    def get_position(self, ticker: str) -> Optional[dict]:
        return self._positions.get(ticker)

    def get_all(self) -> dict[str, dict]:
        return dict(self._positions)

    def total_invested(self) -> float:
        return sum(p["dollars"] for p in self._positions.values())


class SignalBus:
    def __init__(self):
        self.momentum = MomentumTracker()
        self.positions = PositionTracker()
        self._recent_signals: list[dict] = []
        self._recent_intents: list[dict] = []
        self._max_signals = 200

    def emit_signal(self, signal: dict):
        signal["timestamp"] = time.time()
        self._recent_signals.append(signal)
        if len(self._recent_signals) > self._max_signals:
            self._recent_signals = self._recent_signals[-self._max_signals:]
        ticker = signal.get("ticker", "")
        direction = signal.get("direction", "neutral")
        if ticker and direction != "neutral":
            self.momentum.add_signal(ticker, direction)

    def emit_intent(self, intent: dict):
        intent["timestamp"] = time.time()
        self._recent_intents.append(intent)
        if len(self._recent_intents) > 100:
            self._recent_intents = self._recent_intents[-100:]

    def get_recent_signals(self, limit: int = 50) -> list[dict]:
        return self._recent_signals[-limit:]

    def get_recent_intents(self, limit: int = 20) -> list[dict]:
        return self._recent_intents[-limit:]

    def should_trade(self, ticker: str, direction: str) -> dict[str, Any]:
        consensus = self.momentum.get_consensus(ticker)
        if not consensus["consensus"]:
            return {"trade": False, "reason": "No consensus", "consensus": consensus}
        if consensus["direction"] != direction:
            return {"trade": False, "reason": f"Consensus is {consensus['direction']}, not {direction}", "consensus": consensus}
        return {"trade": True, "reason": "Consensus reached", "consensus": consensus}
