from __future__ import annotations

import logging
from typing import Any
from datetime import date

logger = logging.getLogger(__name__)


class PositionSizer:
    def __init__(self, config: dict):
        self.risk_per_trade = config.get("risk_per_trade_pct", 1.0) / 100
        self.max_trade = config.get("max_trade_dollars", 40.0)
        self.min_trade = config.get("min_trade_dollars", 1.0)
        self.atr_mult = config.get("atr_multiplier", 1.8)

    def calculate(self, equity: float, atr: float, price: float, score: float = 0.5) -> float:
        if equity <= 0 or price <= 0:
            return 0
        base = equity * self.risk_per_trade
        vol_adj = 1.0
        if atr > 0 and price > 0:
            vol_pct = atr / price
            vol_adj = min(2.0, 0.02 / max(vol_pct, 0.001))
        conviction = min(abs(score), 1.0)
        half_kelly = conviction * 0.5
        dollars = base * vol_adj * (0.5 + half_kelly * 0.5)
        return round(max(self.min_trade, min(self.max_trade, dollars)), 2)


class CryptoRiskManager:
    def __init__(self, config: dict):
        self.max_daily_loss_pct = config.get("max_daily_loss_pct", 3.0) / 100
        self.max_drawdown_pct = config.get("max_drawdown_pct", 10.0) / 100
        self.max_open_positions = config.get("max_open_positions", 5)
        self._daily_pnl = 0.0
        self._peak_equity = 0.0
        self._last_reset = date.today()
        self._halted = False
        self._halt_reason = ""

    def reset_daily(self):
        today = date.today()
        if today != self._last_reset:
            self._daily_pnl = 0.0
            self._halted = False
            self._halt_reason = ""
            self._last_reset = today

    def record_pnl(self, pnl: float, current_equity: float):
        self.reset_daily()
        self._daily_pnl += pnl
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
        if self._peak_equity > 0:
            dd = (self._peak_equity - current_equity) / self._peak_equity
            if dd >= self.max_drawdown_pct:
                self._halted = True
                self._halt_reason = f"Max drawdown hit: {dd*100:.1f}%"
        if current_equity > 0 and abs(self._daily_pnl) / current_equity >= self.max_daily_loss_pct and self._daily_pnl < 0:
            self._halted = True
            self._halt_reason = f"Daily loss limit: ${self._daily_pnl:.2f}"

    def can_trade(self, open_positions: int) -> dict[str, Any]:
        self.reset_daily()
        if self._halted:
            return {"allowed": False, "reason": self._halt_reason}
        if open_positions >= self.max_open_positions:
            return {"allowed": False, "reason": f"Max positions ({self.max_open_positions}) reached"}
        return {"allowed": True, "reason": ""}

    def status(self) -> dict:
        self.reset_daily()
        return {
            "halted": self._halted,
            "haltReason": self._halt_reason,
            "dailyPnl": round(self._daily_pnl, 2),
            "peakEquity": round(self._peak_equity, 2),
        }


class CryptoPortfolio:
    def __init__(self, max_position_pct: float = 15.0):
        self.max_position_pct = max_position_pct / 100
        self._positions: dict[str, dict] = {}

    def add_position(self, symbol: str, dollars: float, price: float):
        if symbol in self._positions:
            pos = self._positions[symbol]
            pos["dollars"] += dollars
            pos["quantity"] += dollars / price if price > 0 else 0
        else:
            self._positions[symbol] = {
                "dollars": dollars,
                "quantity": dollars / price if price > 0 else 0,
                "entry_price": price,
            }

    def remove_position(self, symbol: str, dollars: float = 0):
        if symbol in self._positions:
            if dollars <= 0 or dollars >= self._positions[symbol]["dollars"]:
                del self._positions[symbol]
            else:
                self._positions[symbol]["dollars"] -= dollars

    def get_positions(self) -> dict[str, dict]:
        return dict(self._positions)

    def open_count(self) -> int:
        return len(self._positions)

    def can_add(self, symbol: str, dollars: float, equity: float) -> bool:
        if equity <= 0:
            return False
        current = self._positions.get(symbol, {}).get("dollars", 0)
        return (current + dollars) / equity <= self.max_position_pct
