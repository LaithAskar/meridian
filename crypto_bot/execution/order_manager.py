from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import robin_stocks.robinhood as rh
    RH_AVAILABLE = True
except ImportError:
    RH_AVAILABLE = False


class OrderManager:
    def __init__(self, dry_run: bool = False, max_spread_pct: float = 1.0):
        self.dry_run = dry_run
        self.max_spread_pct = max_spread_pct
        self._cooldowns: dict[str, float] = {}
        self._cooldown_sec = 30

    def place_order(self, symbol: str, side: str, dollars: float, spread_pct: float = 0) -> Optional[dict]:
        if spread_pct > self.max_spread_pct:
            logger.warning(f"Spread too wide for {symbol}: {spread_pct:.2f}%")
            return None
        now = time.time()
        last = self._cooldowns.get(symbol, 0)
        if now - last < self._cooldown_sec:
            return None
        self._cooldowns[symbol] = now

        if self.dry_run:
            return {
                "symbol": symbol,
                "side": side,
                "dollars": dollars,
                "status": "dry_run_filled",
                "timestamp": time.time(),
            }
        if not RH_AVAILABLE:
            return None
        try:
            order = rh.orders.order_crypto(
                symbol=symbol,
                side=side,
                quantityOrPrice=dollars,
                amountIn="price",
                timeInForce="gtc",
            )
            if order is None or not isinstance(order, dict):
                logger.error(f"Crypto order failed for {symbol}: returned None")
                return None
            if "non_field_errors" in order:
                logger.error(f"Crypto order rejected for {symbol}: {order['non_field_errors']}")
                return None
            return {
                "symbol": symbol,
                "side": side,
                "dollars": dollars,
                "status": "submitted",
                "order_id": order.get("id", ""),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Crypto order error for {symbol}: {e}")
            return None


class SlippageChecker:
    def __init__(self, max_spread_pct: float = 1.0):
        self.max_spread = max_spread_pct

    def check(self, bid: float, ask: float) -> dict:
        mid = (bid + ask) / 2 if (bid + ask) > 0 else 1
        spread = abs(ask - bid) / mid * 100
        return {
            "spread_pct": round(spread, 4),
            "acceptable": spread <= self.max_spread,
            "bid": bid,
            "ask": ask,
        }
