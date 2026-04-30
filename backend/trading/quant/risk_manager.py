from __future__ import annotations

import logging
from typing import Any

from backend.utils.helpers import safe_float, safe_div, clamp

logger = logging.getLogger(__name__)


class QuantRiskManager:
    def __init__(self, max_position_pct: float = 0.08, max_sector_pct: float = 0.25, max_daily_loss_pct: float = 0.03):
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.max_daily_loss_pct = max_daily_loss_pct

    def size_trade(self, signal: dict, equity: float, buying_power: float, volatility: float = 0.02) -> float:
        if equity <= 0 or buying_power <= 0:
            return 0
        score = abs(signal.get("ensembleScore", 0))
        consensus = signal.get("consensus", 0)

        # Base: percentage of equity
        base_pct = self.max_position_pct * min(score * 2, 1.0)

        # Kelly criterion approximation
        win_prob = 0.5 + consensus * 0.15
        win_loss_ratio = 1.5
        kelly = (win_prob * win_loss_ratio - (1 - win_prob)) / win_loss_ratio
        half_kelly = max(0, kelly * 0.5)

        # Volatility adjustment
        vol_adj = clamp(0.02 / max(volatility, 0.005), 0.3, 2.0)

        # Final sizing
        pct = min(base_pct, half_kelly) * vol_adj
        dollars = equity * clamp(pct, 0.01, self.max_position_pct)
        dollars = min(dollars, buying_power * 0.5)
        return round(max(5, dollars), 2)

    def check_drawdown(self, current_equity: float, peak_equity: float) -> dict[str, Any]:
        if peak_equity <= 0:
            return {"ok": True, "drawdown": 0}
        drawdown = (peak_equity - current_equity) / peak_equity
        return {
            "ok": drawdown < 0.10,
            "drawdown": round(drawdown * 100, 2),
            "maxAllowed": 10.0,
        }

    def validate_trade(self, signal: dict, positions: dict, equity: float) -> dict[str, Any]:
        ticker = signal.get("ticker", "")
        direction = signal.get("direction", "")
        if direction == "buy" and ticker in positions:
            current_alloc = positions[ticker].get("dollars", 0)
            if current_alloc / equity > self.max_position_pct:
                return {"allowed": False, "reason": f"Position limit reached for {ticker}"}
        return {"allowed": True, "reason": ""}
