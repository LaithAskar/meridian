from __future__ import annotations

import os
import time
import logging
from datetime import datetime, date
from collections import defaultdict
from typing import Any, Optional

from backend.utils.helpers import safe_float

logger = logging.getLogger(__name__)

try:
    import robin_stocks.robinhood as rh
    RH_AVAILABLE = True
except ImportError:
    RH_AVAILABLE = False
    logger.warning("robin_stocks not available")


class PDTTracker:
    """Track day trades to enforce PDT rule (<$25K accounts)."""

    def __init__(self):
        self._buys: dict[str, list[str]] = defaultdict(list)  # ticker -> [date_str]
        self._sells: dict[str, list[str]] = defaultdict(list)
        self._day_trade_count = 0
        self._day_trade_dates: list[str] = []
        self.max_day_trades = 3
        self.lookback_days = 5

    def record_buy(self, ticker: str):
        today = date.today().isoformat()
        self._buys[ticker].append(today)

    def record_sell(self, ticker: str):
        today = date.today().isoformat()
        self._sells[ticker].append(today)

    def bought_today(self, ticker: str) -> bool:
        today = date.today().isoformat()
        return today in self._buys.get(ticker, [])

    def can_sell_today(self, ticker: str, equity: float = 0) -> bool:
        if equity >= 25000:
            return True
        if self.bought_today(ticker):
            return False
        return self.remaining_day_trades() > 0

    def remaining_day_trades(self) -> int:
        from datetime import timedelta
        cutoff = (date.today() - timedelta(days=self.lookback_days)).isoformat()
        recent = [d for d in self._day_trade_dates if d >= cutoff]
        return max(0, self.max_day_trades - len(recent))

    def cleanup(self):
        from datetime import timedelta
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        for ticker in list(self._buys.keys()):
            self._buys[ticker] = [d for d in self._buys[ticker] if d >= cutoff]
            if not self._buys[ticker]:
                del self._buys[ticker]
        for ticker in list(self._sells.keys()):
            self._sells[ticker] = [d for d in self._sells[ticker] if d >= cutoff]
            if not self._sells[ticker]:
                del self._sells[ticker]


class CircuitBreaker:
    def __init__(self, max_daily_loss_pct: float = 0.03, max_daily_trades: int = 50):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_trades = max_daily_trades
        self._trades_today = 0
        self._daily_pnl = 0.0
        self._starting_equity = 0.0
        self._tripped = False
        self._trip_reason = ""
        self._last_reset = date.today()

    def reset_daily(self):
        today = date.today()
        if today != self._last_reset:
            self._trades_today = 0
            self._daily_pnl = 0.0
            self._tripped = False
            self._trip_reason = ""
            self._last_reset = today

    def record_trade(self, pnl: float = 0):
        self.reset_daily()
        self._trades_today += 1
        self._daily_pnl += pnl
        if self._trades_today >= self.max_daily_trades:
            self._tripped = True
            self._trip_reason = f"Max daily trades reached ({self.max_daily_trades})"
        if self._starting_equity > 0:
            loss_pct = abs(self._daily_pnl) / self._starting_equity
            if self._daily_pnl < 0 and loss_pct >= self.max_daily_loss_pct:
                self._tripped = True
                self._trip_reason = f"Daily loss limit hit ({loss_pct:.1%})"

    def is_tripped(self) -> bool:
        self.reset_daily()
        return self._tripped

    def status(self) -> dict:
        self.reset_daily()
        return {
            "tripped": self._tripped,
            "reason": self._trip_reason,
            "tradesToday": self._trades_today,
            "dailyPnl": round(self._daily_pnl, 2),
        }


class TradeExecutor:
    def __init__(self, paper_mode: bool = False, liquidity_reserve_pct: float = 0.20):
        self.paper_mode = paper_mode
        self.liquidity_reserve_pct = liquidity_reserve_pct
        self.pdt = PDTTracker()
        self.circuit_breaker = CircuitBreaker()
        self._logged_in = False
        self._trade_log: list[dict] = []
        self._cooldowns: dict[str, float] = {}
        self._cooldown_seconds = 60

    def login(self, username: str = "", password: str = ""):
        if not RH_AVAILABLE:
            logger.warning("robin_stocks not available, running in paper mode")
            self.paper_mode = True
            return
        try:
            u = username or os.getenv("ROBINHOOD_USERNAME", "")
            p = password or os.getenv("ROBINHOOD_PASSWORD", "")
            if not u or not p:
                logger.warning("No Robinhood credentials, running in paper mode")
                self.paper_mode = True
                return
            rh.login(u, p, store_session=True)
            self._logged_in = True
            logger.info("Robinhood login successful")
        except Exception as e:
            logger.error(f"Robinhood login failed: {e}")
            self.paper_mode = True

    def get_buying_power(self) -> float:
        if self.paper_mode or not self._logged_in:
            return 10000.0
        try:
            profile = rh.profiles.load_account_profile()
            bp = safe_float(profile.get("buying_power", 0))
            equity = safe_float(profile.get("equity", 0))
            reserve = equity * self.liquidity_reserve_pct
            return max(0, bp - reserve)
        except Exception as e:
            logger.error(f"Error getting buying power: {e}")
            return 0

    def get_equity(self) -> float:
        if self.paper_mode or not self._logged_in:
            return 10000.0
        try:
            profile = rh.profiles.load_account_profile()
            return safe_float(profile.get("equity", 0))
        except Exception:
            return 0

    def _in_cooldown(self, ticker: str) -> bool:
        last = self._cooldowns.get(ticker, 0)
        return (time.time() - last) < self._cooldown_seconds

    def execute_buy(self, ticker: str, dollars: float, reason: str = "") -> Optional[dict]:
        if self.circuit_breaker.is_tripped():
            logger.warning(f"Circuit breaker tripped, skipping buy for {ticker}")
            return None
        if self._in_cooldown(ticker):
            return None
        if dollars < 1:
            return None

        self.pdt.record_buy(ticker)
        self._cooldowns[ticker] = time.time()

        trade_record = {
            "ticker": ticker,
            "side": "buy",
            "dollars": round(dollars, 2),
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "paper": self.paper_mode,
        }

        if self.paper_mode:
            trade_record["status"] = "paper_filled"
            trade_record["order_id"] = f"paper_{int(time.time())}"
        else:
            try:
                order = rh.orders.order_buy_fractional_by_price(
                    ticker, dollars, timeInForce="gfd"
                )
                if order is None or not isinstance(order, dict):
                    trade_record["status"] = "failed"
                    trade_record["error"] = "Order returned None"
                elif "non_field_errors" in order:
                    trade_record["status"] = "rejected"
                    trade_record["error"] = str(order["non_field_errors"])
                else:
                    trade_record["status"] = "submitted"
                    trade_record["order_id"] = order.get("id", "unknown")
            except Exception as e:
                trade_record["status"] = "error"
                trade_record["error"] = str(e)

        self._trade_log.append(trade_record)
        self.circuit_breaker.record_trade()
        logger.info(f"BUY {ticker} ${dollars:.2f} - {trade_record.get('status')} - {reason}")
        return trade_record

    def execute_sell(self, ticker: str, dollars: float, reason: str = "") -> Optional[dict]:
        if self.circuit_breaker.is_tripped():
            return None
        equity = self.get_equity()
        if not self.pdt.can_sell_today(ticker, equity):
            logger.warning(f"PDT rule: cannot sell {ticker} today (bought today or no day trades left)")
            return None
        if self._in_cooldown(ticker):
            return None

        self._cooldowns[ticker] = time.time()
        trade_record = {
            "ticker": ticker,
            "side": "sell",
            "dollars": round(dollars, 2),
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "paper": self.paper_mode,
        }

        if self.paper_mode:
            trade_record["status"] = "paper_filled"
            trade_record["order_id"] = f"paper_{int(time.time())}"
        else:
            try:
                order = rh.orders.order_sell_fractional_by_price(
                    ticker, dollars, timeInForce="gfd"
                )
                if order is None or not isinstance(order, dict):
                    trade_record["status"] = "failed"
                    trade_record["error"] = "Order returned None"
                elif "non_field_errors" in order:
                    trade_record["status"] = "rejected"
                    trade_record["error"] = str(order["non_field_errors"])
                else:
                    trade_record["status"] = "submitted"
                    trade_record["order_id"] = order.get("id", "unknown")
            except Exception as e:
                trade_record["status"] = "error"
                trade_record["error"] = str(e)

        self._trade_log.append(trade_record)
        self.circuit_breaker.record_trade()
        logger.info(f"SELL {ticker} ${dollars:.2f} - {trade_record.get('status')} - {reason}")
        return trade_record

    def get_trade_log(self, limit: int = 50) -> list[dict]:
        return self._trade_log[-limit:]

    def get_stats(self) -> dict:
        total = len(self._trade_log)
        buys = sum(1 for t in self._trade_log if t["side"] == "buy")
        sells = sum(1 for t in self._trade_log if t["side"] == "sell")
        return {
            "totalTrades": total,
            "buys": buys,
            "sells": sells,
            "circuitBreaker": self.circuit_breaker.status(),
            "pdtRemaining": self.pdt.remaining_day_trades(),
            "paperMode": self.paper_mode,
            "loggedIn": self._logged_in,
        }
