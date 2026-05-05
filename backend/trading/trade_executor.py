from __future__ import annotations

import os
import time
import logging
from datetime import datetime, date
from collections import defaultdict
from typing import Any, Callable, Optional

from backend.utils.helpers import safe_float

logger = logging.getLogger(__name__)

try:
    import robin_stocks.robinhood as rh
    RH_AVAILABLE = True
except ImportError:
    RH_AVAILABLE = False
    logger.warning("robin_stocks not available")


def _classify_order_response(order: Any, trade_record: dict) -> None:
    """Robinhood may return non_field_errors as warnings on a successful submit.
    Source of truth is the order id — if present, the order was accepted."""
    if order is None or not isinstance(order, dict):
        trade_record["status"] = "failed"
        trade_record["error"] = "Order returned None"
        return
    order_id = order.get("id")
    if order_id:
        trade_record["status"] = "submitted"
        trade_record["order_id"] = order_id
        if "non_field_errors" in order:
            trade_record["warning"] = str(order["non_field_errors"])
    elif "non_field_errors" in order:
        trade_record["status"] = "rejected"
        trade_record["error"] = str(order["non_field_errors"])
    else:
        trade_record["status"] = "failed"
        trade_record["error"] = f"Unexpected response shape: {list(order.keys())[:5]}"


def _log_trade(side: str, ticker: str, dollars: float, trade_record: dict, reason: str) -> None:
    detail = trade_record.get("error") or trade_record.get("warning") or ""
    detail_part = f" [{detail}]" if detail else ""
    logger.info(
        f"{side} {ticker} ${dollars:.2f} - {trade_record.get('status')}{detail_part} - {reason}"
    )


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
    def __init__(
        self,
        max_daily_loss_pct: float = 0.03,
        max_daily_trades: int = 50,
        equity_provider: Optional[Callable[[], float]] = None,
        max_consecutive_failures: int = 5,
    ):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_trades = max_daily_trades
        self.max_consecutive_failures = max_consecutive_failures
        self._equity_provider = equity_provider
        self._trades_today = 0
        self._daily_pnl = 0.0
        self._starting_equity = 0.0
        self._consecutive_failures = 0
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
            self._starting_equity = 0.0
            self._consecutive_failures = 0
            self._last_reset = today

    def prime_starting_equity(self, equity: float) -> None:
        if self._starting_equity == 0.0 and equity > 0:
            self._starting_equity = equity
            logger.info(f"CircuitBreaker primed: starting_equity=${equity:.2f}, loss_halt=${equity * self.max_daily_loss_pct:.2f}")

    def record_trade(self):
        self.reset_daily()
        self._trades_today += 1
        self._consecutive_failures = 0
        if self._trades_today >= self.max_daily_trades:
            self._tripped = True
            self._trip_reason = f"Max daily trades reached ({self.max_daily_trades})"

    def record_failure(self):
        self.reset_daily()
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.max_consecutive_failures:
            self._tripped = True
            self._trip_reason = f"Consecutive-failure halt ({self._consecutive_failures} non-fills)"

    def _refresh_pnl(self) -> None:
        if self._starting_equity <= 0 or self._equity_provider is None:
            return
        try:
            current = self._equity_provider()
        except Exception as e:
            logger.warning(f"CircuitBreaker equity probe failed: {e}")
            return
        if current <= 0:
            return
        self._daily_pnl = current - self._starting_equity
        if self._daily_pnl < 0:
            loss_pct = abs(self._daily_pnl) / self._starting_equity
            if loss_pct >= self.max_daily_loss_pct:
                self._tripped = True
                self._trip_reason = f"Daily loss limit hit ({loss_pct:.1%}, ${self._daily_pnl:.2f})"

    def is_tripped(self) -> bool:
        self.reset_daily()
        if not self._tripped:
            self._refresh_pnl()
        return self._tripped

    def status(self) -> dict:
        self.reset_daily()
        if not self._tripped:
            self._refresh_pnl()
        return {
            "tripped": self._tripped,
            "reason": self._trip_reason,
            "tradesToday": self._trades_today,
            "dailyPnl": round(self._daily_pnl, 2),
            "startingEquity": round(self._starting_equity, 2),
            "consecutiveFailures": self._consecutive_failures,
        }


class TradeExecutor:
    def __init__(
        self,
        paper_mode: bool = False,
        liquidity_reserve_pct: float = 0.20,
        max_daily_trades: int = 50,
        max_daily_loss_pct: float = 0.03,
    ):
        self.paper_mode = paper_mode
        self.liquidity_reserve_pct = liquidity_reserve_pct
        self.pdt = PDTTracker()
        self.circuit_breaker = CircuitBreaker(
            max_daily_loss_pct=max_daily_loss_pct,
            max_daily_trades=max_daily_trades,
            equity_provider=self.get_equity,
        )
        self._logged_in = False
        self._trade_log: list[dict] = []
        self._cooldowns: dict[str, float] = {}
        self._cooldown_seconds = 60
        # TTL cache for account snapshots — Robinhood 429s when hammered.
        # 10s is short enough that loss-halt detection lag is negligible
        # (max possible $-loss in 10s on $10 trades is well under the $20 budget).
        self._snapshot_ttl = 10.0
        self._bp_cache: tuple[float, float] = (0.0, 0.0)
        self._equity_cache: tuple[float, float] = (0.0, 0.0)
        # Inter-order spacing — RH's POST /orders endpoint 429s under burst load.
        self._order_min_spacing = 3.0
        self._last_order_time = 0.0

    def _throttle_order(self) -> None:
        if self.paper_mode:
            return
        elapsed = time.time() - self._last_order_time
        if elapsed < self._order_min_spacing:
            time.sleep(self._order_min_spacing - elapsed)
        self._last_order_time = time.time()

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    def login(self, username: str = "", password: str = ""):
        if self.paper_mode:
            logger.info("TRADING_PAPER_MODE=true — skipping Robinhood login")
            return
        if not RH_AVAILABLE:
            raise RuntimeError(
                "real-money mode requires robin_stocks library, but it is not installed"
            )
        u = username or os.getenv("ROBINHOOD_USERNAME", "")
        p = password or os.getenv("ROBINHOOD_PASSWORD", "")
        if not u or not p:
            raise RuntimeError(
                "real-money mode requires ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD env vars"
            )
        try:
            rh.login(u, p, store_session=True)
        except Exception as e:
            logger.error(f"Robinhood login failed: {e}")
            raise RuntimeError("Robinhood login failed (see backend log for details)") from e
        self._logged_in = True
        logger.info("Robinhood login successful")
        equity = self.get_equity()
        self.circuit_breaker.prime_starting_equity(equity)
        self._maybe_prime_pdt_from_holdings()

    def _maybe_prime_pdt_from_holdings(self) -> None:
        """Prime PDT bought_today AND breaker tradesToday from RH order history.
        - PDT: mark only tickers with FILLED BUY orders today as bought_today
          (yesterday's positions stay sellable, today's fills get day-trade
          protection).
        - Breaker tradesToday: count ALL submissions today (filled, rejected,
          any state). Mirrors in-memory semantic where record_trade fires on
          submission, not fill. Keeps the cap meaningful across restarts."""
        state_file = os.path.expanduser("~/.meridian_last_run")
        today = date.today().isoformat()
        try:
            with open(state_file, "w") as f:
                f.write(today)
        except Exception as e:
            logger.warning(f"Could not write last-run state: {e}")

        try:
            orders = rh.orders.get_all_stock_orders() or []
        except Exception as e:
            logger.warning(f"PDT/breaker prime: could not fetch order history: {e}")
            return

        symbol_cache: dict[str, str] = {}
        today_bought: set[str] = set()
        today_submission_count = 0
        for o in orders:
            if not isinstance(o, dict):
                continue
            if not o.get("created_at", "").startswith(today):
                continue
            today_submission_count += 1
            if o.get("side") != "buy" or o.get("state") != "filled":
                continue
            url = o.get("instrument", "")
            if not url:
                continue
            sym = symbol_cache.get(url)
            if sym is None:
                try:
                    inst = rh.stocks.get_instrument_by_url(url) or {}
                    sym = inst.get("symbol", "") or ""
                except Exception:
                    sym = ""
                symbol_cache[url] = sym
            if sym:
                today_bought.add(sym)

        for ticker in today_bought:
            self.pdt.record_buy(ticker)

        if today_submission_count > 0:
            self.circuit_breaker._trades_today = today_submission_count
            cap = self.circuit_breaker.max_daily_trades
            if today_submission_count >= cap:
                self.circuit_breaker._tripped = True
                self.circuit_breaker._trip_reason = f"Max daily trades reached ({cap}) — primed from RH history"

        if today_bought:
            logger.info(f"PDT primed from RH (today's filled buys, sells blocked): {sorted(today_bought)}")
        if today_submission_count > 0:
            logger.info(f"Breaker tradesToday primed from RH: {today_submission_count}/{self.circuit_breaker.max_daily_trades} submissions today")
        if not today_bought and today_submission_count == 0:
            logger.info("PDT/breaker prime: no same-day RH activity found")

    def get_buying_power(self) -> float:
        if self.paper_mode or not self._logged_in:
            return 10000.0
        now = time.time()
        cached_at, cached = self._bp_cache
        if now - cached_at < self._snapshot_ttl:
            return cached
        try:
            account = rh.profiles.load_account_profile()
            portfolio = rh.profiles.load_portfolio_profile()
            if not isinstance(account, dict) or not isinstance(portfolio, dict):
                raise RuntimeError("Robinhood returned non-dict profile (likely rate-limited)")
            bp = safe_float(account.get("buying_power", 0))
            equity = safe_float(portfolio.get("equity", 0))
            reserve = equity * self.liquidity_reserve_pct
            value = max(0, bp - reserve)
        except Exception as e:
            logger.error(f"Error getting buying power: {e}")
            return cached if cached_at > 0 else 0
        self._bp_cache = (now, value)
        return value

    def get_equity(self) -> float:
        if self.paper_mode or not self._logged_in:
            return 10000.0
        now = time.time()
        cached_at, cached = self._equity_cache
        if now - cached_at < self._snapshot_ttl:
            return cached
        try:
            portfolio = rh.profiles.load_portfolio_profile()
            if not isinstance(portfolio, dict):
                raise RuntimeError("Robinhood returned non-dict portfolio (likely rate-limited)")
            value = safe_float(portfolio.get("equity", 0))
        except Exception as e:
            logger.error(f"Error getting equity: {e}")
            return cached if cached_at > 0 else 0
        self._equity_cache = (now, value)
        return value

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
                self._throttle_order()
                order = rh.orders.order_buy_fractional_by_price(
                    ticker, dollars, timeInForce="gfd"
                )
                _classify_order_response(order, trade_record)
            except Exception as e:
                trade_record["status"] = "error"
                trade_record["error"] = str(e)

        # Cooldown applies to any attempt to prevent rapid retries on rejection.
        # PDT tracking and circuit-breaker counting only on actual fills/submissions.
        self._cooldowns[ticker] = time.time()
        if trade_record.get("status") in ("paper_filled", "submitted"):
            self.pdt.record_buy(ticker)
            self.circuit_breaker.record_trade()
        else:
            self.circuit_breaker.record_failure()

        self._trade_log.append(trade_record)
        _log_trade("BUY", ticker, dollars, trade_record, reason)
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
                self._throttle_order()
                order = rh.orders.order_sell_fractional_by_price(
                    ticker, dollars, timeInForce="gfd"
                )
                _classify_order_response(order, trade_record)
            except Exception as e:
                trade_record["status"] = "error"
                trade_record["error"] = str(e)

        self._cooldowns[ticker] = time.time()
        if trade_record.get("status") in ("paper_filled", "submitted"):
            self.pdt.record_sell(ticker)
            self.circuit_breaker.record_trade()
        else:
            self.circuit_breaker.record_failure()

        self._trade_log.append(trade_record)
        _log_trade("SELL", ticker, dollars, trade_record, reason)
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
