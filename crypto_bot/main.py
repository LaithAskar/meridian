from __future__ import annotations

import os
import sys
import time
import logging
from datetime import datetime

import yaml
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crypto_bot")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto_bot.auth.robinhood_auth import RobinhoodAuth
from crypto_bot.data.market_data import MarketData
from crypto_bot.strategy.signal_engine import SignalEngine
from crypto_bot.risk.risk_manager import PositionSizer, CryptoRiskManager, CryptoPortfolio
from crypto_bot.execution.order_manager import OrderManager
from crypto_bot.logging_.trade_logger import TradeLogger
from crypto_bot.utils.rate_limiter import RateLimiter
from crypto_bot.utils.helpers import safe_float
from crypto_bot.indicators.technical import atr as compute_atr


def load_config() -> dict:
    path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def main():
    config = load_config()
    coins = config.get("coins", ["BTC", "ETH", "SOL"])
    cycle_minutes = config.get("cycle_interval_minutes", 2)
    dry_run = config.get("dry_run", False)
    sig_config = config.get("signals", {})
    risk_config = config.get("risk", {})
    exec_config = config.get("execution", {})

    auth = RobinhoodAuth()
    if not dry_run:
        if not auth.login():
            logger.error("Cannot login to Robinhood, switching to dry run")
            dry_run = True

    market = MarketData()
    engine = SignalEngine(sig_config)
    sizer = PositionSizer(risk_config)
    risk_mgr = CryptoRiskManager(risk_config)
    portfolio = CryptoPortfolio(risk_config.get("max_position_pct", 15.0))
    order_mgr = OrderManager(dry_run=dry_run, max_spread_pct=exec_config.get("max_spread_pct", 1.0))
    trade_log = TradeLogger()
    rate_limiter = RateLimiter()

    logger.info(f"Crypto bot started - coins={coins}, cycle={cycle_minutes}min, dry_run={dry_run}")

    while True:
        cycle_start = time.time()
        try:
            for symbol in coins:
                with rate_limiter:
                    try:
                        df = market.get_crypto_historicals(symbol, interval="hour", span="week")
                        if df is None or df.empty:
                            continue

                        quote = market.get_crypto_quote(symbol)
                        price = quote.get("price", 0) if quote else 0
                        if price <= 0:
                            continue

                        signal = engine.evaluate(symbol, df)
                        action = signal["action"]

                        if action == "HOLD":
                            continue

                        check = risk_mgr.can_trade(portfolio.open_count())
                        if not check["allowed"]:
                            logger.info(f"Risk block for {symbol}: {check['reason']}")
                            continue

                        spread = market.get_spread(symbol)
                        atr_val = 0
                        try:
                            a = compute_atr(df["high"], df["low"], df["close"], 14)
                            atr_val = float(a.iloc[-1]) if len(a) > 0 else 0
                        except Exception:
                            pass

                        equity = 10000 if dry_run else safe_float(
                            getattr(__import__("robin_stocks.robinhood", fromlist=["profiles"]).profiles, "load_portfolio_profile", lambda: {})().get("equity", 0)
                        )

                        if action == "BUY":
                            if not portfolio.can_add(symbol, 0, equity):
                                continue
                            dollars = sizer.calculate(equity, atr_val, price, signal["score"])
                            result = order_mgr.place_order(symbol, "buy", dollars, spread)
                            if result:
                                portfolio.add_position(symbol, dollars, price)
                                trade_log.log_trade({
                                    "timestamp": datetime.now().isoformat(),
                                    "symbol": symbol,
                                    "side": "buy",
                                    "dollars": dollars,
                                    "price": price,
                                    "score": signal["score"],
                                    "regime": signal.get("regime", ""),
                                    "confirmations": signal.get("confirmations", 0),
                                    "status": result.get("status", ""),
                                    "order_id": result.get("order_id", ""),
                                })
                                logger.info(f"BUY {symbol} ${dollars:.2f} @ ${price:.2f} score={signal['score']:.3f}")

                        elif action == "SELL":
                            pos = portfolio.get_positions().get(symbol)
                            if not pos:
                                continue
                            dollars = min(pos["dollars"], risk_config.get("max_trade_dollars", 40))
                            result = order_mgr.place_order(symbol, "sell", dollars, spread)
                            if result:
                                pnl = (price - pos.get("entry_price", price)) / pos.get("entry_price", price) * dollars
                                portfolio.remove_position(symbol, dollars)
                                risk_mgr.record_pnl(pnl, equity)
                                engine.adaptive.record(pnl > 0)
                                trade_log.log_trade({
                                    "timestamp": datetime.now().isoformat(),
                                    "symbol": symbol,
                                    "side": "sell",
                                    "dollars": dollars,
                                    "price": price,
                                    "score": signal["score"],
                                    "regime": signal.get("regime", ""),
                                    "confirmations": signal.get("confirmations", 0),
                                    "status": result.get("status", ""),
                                    "order_id": result.get("order_id", ""),
                                    "pnl": round(pnl, 2),
                                })
                                logger.info(f"SELL {symbol} ${dollars:.2f} @ ${price:.2f} pnl=${pnl:.2f}")

                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {e}")

        except Exception as e:
            logger.error(f"Cycle error: {e}")

        elapsed = time.time() - cycle_start
        sleep_time = max(0, cycle_minutes * 60 - elapsed)
        logger.debug(f"Cycle done in {elapsed:.1f}s, sleeping {sleep_time:.0f}s")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
