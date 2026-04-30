from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PDTGuard:
    """Wraps PDTTracker for quant engine use."""

    def __init__(self, pdt_tracker):
        self.pdt = pdt_tracker

    def filter_signals(self, signals: list[dict], equity: float = 0) -> list[dict]:
        filtered = []
        for sig in signals:
            ticker = sig.get("ticker", "")
            direction = sig.get("direction", "")
            if direction == "sell":
                if not self.pdt.can_sell_today(ticker, equity):
                    sig["blocked"] = True
                    sig["blockReason"] = "PDT rule: bought today"
                    continue
            filtered.append(sig)
        return filtered
