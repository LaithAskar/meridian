"""Position exit rules.

TimeStop: force-liquidate positions whose oldest filled buy is older than
N business days. PDT-safe by construction — a 5-day-old position cannot
be a day trade.

Live-mode only: derives position ages from Robinhood order history. Paper
mode is a no-op (no real positions to stop). When the bot returns to live
mode, TimeStop will start managing positions immediately.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _business_days_between(d1: date, d2: date) -> int:
    """Business days between two dates (excludes weekends, ignores holidays)."""
    if d1 > d2:
        d1, d2 = d2, d1
    days = 0
    cur = d1
    while cur < d2:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


class TimeStop:
    def __init__(self, holding_days: int = 5, scan_interval_seconds: float = 60.0):
        self.holding_days = holding_days
        self._scan_interval = scan_interval_seconds
        self._last_scan = 0.0
        self._already_exited: set[str] = set()  # tickers we've issued exit for this session

    def reset_for_new_day(self) -> None:
        self._already_exited.clear()

    def get_positions_to_exit(self, rh_module: Any) -> list[dict]:
        """Returns list of {ticker, quantity, days_held, oldest_buy_date}
        for positions older than holding_days. Throttled to scan_interval
        to avoid hammering RH order history endpoint."""
        if time.time() - self._last_scan < self._scan_interval:
            return []
        self._last_scan = time.time()

        try:
            holdings = rh_module.account.build_holdings() or {}
            orders = rh_module.orders.get_all_stock_orders() or []
        except Exception as e:
            logger.warning(f"TimeStop: RH fetch failed: {e}")
            return []

        if not holdings:
            return []

        # Find oldest filled buy date per symbol via order history
        oldest_buys: dict[str, date] = {}
        symbol_cache: dict[str, str] = {}
        for o in orders:
            if not isinstance(o, dict):
                continue
            if o.get("side") != "buy" or o.get("state") != "filled":
                continue
            url = o.get("instrument", "")
            if not url:
                continue
            sym = symbol_cache.get(url)
            if sym is None:
                try:
                    inst = rh_module.stocks.get_instrument_by_url(url) or {}
                    sym = inst.get("symbol", "") or ""
                except Exception:
                    sym = ""
                symbol_cache[url] = sym
            if not sym:
                continue
            created = o.get("created_at", "")
            if not created or len(created) < 10:
                continue
            try:
                buy_date = date.fromisoformat(created[:10])
            except Exception:
                continue
            if sym not in oldest_buys or buy_date < oldest_buys[sym]:
                oldest_buys[sym] = buy_date

        today = date.today()
        results = []
        for ticker, holding in holdings.items():
            if ticker in self._already_exited:
                continue
            if ticker not in oldest_buys:
                continue
            days_held = _business_days_between(oldest_buys[ticker], today)
            if days_held < self.holding_days:
                continue
            try:
                quantity = float(holding.get("quantity", "0"))
                price = float(holding.get("price", "0"))
            except (TypeError, ValueError):
                continue
            if quantity <= 0:
                continue
            results.append({
                "ticker": ticker,
                "quantity": quantity,
                "dollars": round(quantity * price, 2),
                "days_held": days_held,
                "oldest_buy_date": oldest_buys[ticker].isoformat(),
            })
        return results

    def mark_exited(self, ticker: str) -> None:
        self._already_exited.add(ticker)
