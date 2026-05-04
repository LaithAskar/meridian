from __future__ import annotations

import os
import sys
import logging
import subprocess
from typing import Any, Optional
from contextlib import asynccontextmanager

# Load .env before backend.* imports — BotConfig.from_yaml() reads
# TRADING_PAPER_MODE at module-import time (backend/trading/config.py).
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.services.data_service import (
    get_quote, get_history, get_info, get_financials,
    get_earnings, search_tickers, get_analyst_info, POPULAR_TICKERS,
)
from backend.services.technical import get_technical_analysis
from backend.services.fundamental import get_fundamental_analysis
from backend.services.sentiment import get_news_sentiment
from backend.services.portfolio import optimize_portfolio
from backend.models.ensemble import predict_ensemble
from backend.trading.config import BotConfig
from backend.trading.stream_ingestor import StreamIngestor
from backend.utils.helpers import safe_float

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Global state ────────────────────────────────────────────
config_path = os.path.join(os.path.dirname(__file__), "trading_config.yaml")
bot_config = BotConfig.from_yaml(config_path)
ingestor: Optional[StreamIngestor] = None
_rh_logged_in = False

# ── Robinhood helpers ───────────────────────────────────────
try:
    import robin_stocks.robinhood as rh
    RH_AVAILABLE = True
except ImportError:
    RH_AVAILABLE = False


def _rh_login(username: str = "", password: str = "") -> dict:
    global _rh_logged_in
    if not RH_AVAILABLE:
        return {"success": False, "error": "robin_stocks not installed"}
    try:
        u = username or os.getenv("ROBINHOOD_USERNAME", "")
        p = password or os.getenv("ROBINHOOD_PASSWORD", "")
        if not u or not p:
            return {"success": False, "error": "No credentials provided"}
        rh.login(u, p, store_session=True)
        _rh_logged_in = True
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Lifespan ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingestor
    logger.info("Meridian backend starting up")
    # Auto-start trading bot
    ingestor = StreamIngestor(bot_config)
    try:
        ingestor.start()
        # Synchronize legacy module-level flag with executor login state so
        # /api/robinhood/* endpoints reflect the bot's auto-login.
        global _rh_logged_in
        if ingestor.executor.is_logged_in:
            _rh_logged_in = True
        logger.info("Trading bot auto-started")
    except RuntimeError as e:
        # Real-money login failures raise RuntimeError — fail startup loudly so
        # uvicorn aborts and the backend never serves with a non-functional bot.
        logger.critical(f"FATAL startup error: {e}")
        raise
    except Exception as e:
        logger.warning(f"Could not auto-start trading bot (non-critical): {e}")
    yield
    if ingestor and ingestor._running:
        ingestor.stop()
    logger.info("Meridian backend shut down")


app = FastAPI(
    title="Meridian Stock Analysis API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ────────────────────────────────────────
class PortfolioRequest(BaseModel):
    tickers: list[str]
    investment_amount: float = 10000
    risk_tolerance: str = "moderate"

class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""

class OrderRequest(BaseModel):
    ticker: str
    side: str  # "buy" or "sell"
    dollars: float

# ════════════════════════════════════════════════════════════
#  STOCK DATA ROUTES
# ════════════════════════════════════════════════════════════

@app.get("/")
def health():
    return {"message": "Meridian Stock Analysis API", "version": "1.0.0"}


@app.get("/api/search")
def api_search(q: str = Query("")):
    return search_tickers(q)


@app.get("/api/quote/{ticker}")
def api_quote(ticker: str):
    return get_quote(ticker)


@app.get("/api/history/{ticker}")
def api_history(ticker: str, period: str = "1y", interval: str = "1d"):
    return get_history(ticker, period, interval)


@app.get("/api/analysis/{ticker}")
def api_analysis(ticker: str):
    fundamental = get_fundamental_analysis(ticker)
    technical = get_technical_analysis(ticker)
    quote = get_quote(ticker)
    return {
        "ticker": ticker.upper(),
        "quote": quote,
        "fundamental": fundamental,
        "technical": technical,
    }


@app.get("/api/news/{ticker}")
def api_news(ticker: str):
    return get_news_sentiment(ticker)


@app.get("/api/earnings/{ticker}")
def api_earnings(ticker: str):
    return get_earnings(ticker)


@app.get("/api/financials/{ticker}")
def api_financials(ticker: str):
    return get_financials(ticker)


@app.get("/api/analysts/{ticker}")
def api_analysts(ticker: str):
    return get_analyst_info(ticker)


@app.get("/api/predict/{ticker}")
def api_predict(ticker: str, days: int = Query(30, ge=1, le=90)):
    return predict_ensemble(ticker, days)


@app.post("/api/portfolio")
def api_portfolio(req: PortfolioRequest):
    return optimize_portfolio(
        tickers=req.tickers,
        investment_amount=req.investment_amount,
        risk_tolerance=req.risk_tolerance,
    )


@app.get("/api/trending")
def api_trending():
    if ingestor:
        trending = ingestor.ticker_extractor.get_trending()
        return {"trending": trending}
    return {"trending": []}


# ════════════════════════════════════════════════════════════
#  TRADING BOT ROUTES
# ════════════════════════════════════════════════════════════

@app.post("/api/trading/start")
def trading_start():
    global ingestor
    if ingestor and ingestor._running:
        return {"status": "already_running"}
    ingestor = StreamIngestor(bot_config)
    ingestor.start()
    return {"status": "started"}


@app.post("/api/trading/stop")
def trading_stop():
    if ingestor and ingestor._running:
        ingestor.stop()
        return {"status": "stopped"}
    return {"status": "not_running"}


@app.get("/api/trading/status")
def trading_status():
    if ingestor:
        return ingestor.get_status()
    return {"running": False, "stats": {}, "recentTrades": [], "trending": []}


@app.get("/api/trading/signals")
def trading_signals():
    if ingestor:
        return ingestor.get_signals()
    return {"signals": [], "intents": []}


@app.get("/api/trading/config")
def trading_config():
    return bot_config.to_dict()


@app.websocket("/ws/trading/signals")
async def ws_trading(websocket: WebSocket):
    await websocket.accept()
    if ingestor:
        ingestor._ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if ingestor and websocket in ingestor._ws_clients:
            ingestor._ws_clients.remove(websocket)


# ════════════════════════════════════════════════════════════
#  ROBINHOOD ACCOUNT ROUTES
# ════════════════════════════════════════════════════════════

@app.get("/api/robinhood/status")
def rh_status():
    return {"connected": _rh_logged_in, "available": RH_AVAILABLE}


@app.post("/api/robinhood/login")
def rh_login(req: LoginRequest):
    result = _rh_login(req.username, req.password)
    return result


@app.get("/api/robinhood/account")
def rh_account():
    if not _rh_logged_in or not RH_AVAILABLE:
        return {"error": "Not connected to Robinhood"}
    try:
        profile = rh.profiles.load_account_profile()
        portfolio = rh.profiles.load_portfolio_profile()
        return {
            "equity": safe_float(portfolio.get("equity")),
            "extendedHoursEquity": safe_float(portfolio.get("extended_hours_equity")),
            "marketValue": safe_float(portfolio.get("market_value")),
            "buyingPower": safe_float(profile.get("buying_power")),
            "cash": safe_float(profile.get("cash")),
            "todayPnl": safe_float(portfolio.get("equity")) - safe_float(portfolio.get("adjusted_equity_previous_close")),
            "totalPnl": safe_float(portfolio.get("equity")) - safe_float(portfolio.get("adjusted_portfolio_equity_previous_close")),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/robinhood/positions")
def rh_positions():
    if not _rh_logged_in or not RH_AVAILABLE:
        return []
    try:
        positions = rh.account.get_open_stock_positions()
        result = []
        for pos in positions or []:
            ticker = ""
            instrument = pos.get("instrument", "")
            if instrument:
                try:
                    inst_data = rh.stocks.get_instrument_by_url(instrument)
                    ticker = inst_data.get("symbol", "") if inst_data else ""
                except Exception:
                    pass
            qty = safe_float(pos.get("quantity"))
            avg_cost = safe_float(pos.get("average_buy_price"))
            current = 0
            if ticker:
                try:
                    quote = rh.stocks.get_latest_price(ticker)
                    current = safe_float(quote[0]) if quote else 0
                except Exception:
                    pass
            market_value = qty * current
            cost_basis = qty * avg_cost
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0
            result.append({
                "ticker": ticker,
                "quantity": round(qty, 6),
                "averageCost": round(avg_cost, 2),
                "currentPrice": round(current, 2),
                "marketValue": round(market_value, 2),
                "costBasis": round(cost_basis, 2),
                "pnl": round(pnl, 2),
                "pnlPercent": round(pnl_pct, 2),
            })
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/robinhood/history")
def rh_history():
    if not _rh_logged_in or not RH_AVAILABLE:
        return []
    try:
        orders = rh.orders.get_all_stock_orders()
        result = []
        for order in (orders or [])[:50]:
            result.append({
                "id": order.get("id", ""),
                "side": order.get("side", ""),
                "ticker": order.get("symbol", "") or "",
                "quantity": safe_float(order.get("quantity")),
                "price": safe_float(order.get("average_price") or order.get("price")),
                "state": order.get("state", ""),
                "type": order.get("type", ""),
                "createdAt": order.get("created_at", ""),
            })
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/robinhood/watchlist")
def rh_watchlist():
    if not _rh_logged_in or not RH_AVAILABLE:
        return []
    try:
        watchlist = rh.account.get_watchlist_by_name()
        return watchlist or []
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/robinhood/order")
def rh_order(req: OrderRequest):
    if not _rh_logged_in or not RH_AVAILABLE:
        return {"error": "Not connected to Robinhood"}
    try:
        if req.side == "buy":
            order = rh.orders.order_buy_fractional_by_price(req.ticker, req.dollars, timeInForce="gfd")
        elif req.side == "sell":
            order = rh.orders.order_sell_fractional_by_price(req.ticker, req.dollars, timeInForce="gfd")
        else:
            return {"error": "Invalid side, must be 'buy' or 'sell'"}
        if order is None or not isinstance(order, dict):
            return {"error": "Order failed - returned None"}
        if "non_field_errors" in order:
            return {"error": str(order["non_field_errors"])}
        return {"success": True, "orderId": order.get("id")}
    except Exception as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════
#  CRYPTO BOT ROUTES
# ════════════════════════════════════════════════════════════

_crypto_process = None

@app.get("/api/crypto/status")
def crypto_status():
    global _crypto_process
    running = _crypto_process is not None and _crypto_process.poll() is None
    trades = []
    try:
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "..", "crypto_bot", "trades.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 50")
            trades = [dict(r) for r in cur.fetchall()]
            conn.close()
    except Exception:
        pass
    return {"running": running, "trades": trades}


@app.post("/api/crypto/start")
def crypto_start():
    global _crypto_process
    if _crypto_process and _crypto_process.poll() is None:
        return {"status": "already_running"}
    try:
        bot_path = os.path.join(os.path.dirname(__file__), "..", "crypto_bot", "main.py")
        _crypto_process = subprocess.Popen(
            [sys.executable, bot_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"status": "started", "pid": _crypto_process.pid}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/crypto/stop")
def crypto_stop():
    global _crypto_process
    if _crypto_process and _crypto_process.poll() is None:
        _crypto_process.terminate()
        _crypto_process = None
        return {"status": "stopped"}
    return {"status": "not_running"}


@app.get("/api/crypto/prices")
def crypto_prices():
    coins = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOGE", "SHIB", "XLM"]
    prices = {}
    if _rh_logged_in and RH_AVAILABLE:
        for coin in coins:
            try:
                quote = rh.crypto.get_crypto_quote(coin)
                if quote:
                    prices[coin] = {
                        "price": safe_float(quote.get("mark_price")),
                        "bid": safe_float(quote.get("bid_price")),
                        "ask": safe_float(quote.get("ask_price")),
                        "high": safe_float(quote.get("high_price")),
                        "low": safe_float(quote.get("low_price")),
                        "volume": safe_float(quote.get("volume")),
                    }
            except Exception:
                prices[coin] = {"price": 0, "error": "Failed to fetch"}
    else:
        for coin in coins:
            prices[coin] = {"price": 0, "note": "Not connected to Robinhood"}
    return prices


# ── Run ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
