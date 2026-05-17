from __future__ import annotations

import os
import logging
from typing import Optional
from contextlib import asynccontextmanager

# Load .env before backend.* imports — BotConfig.from_yaml() reads
# TRADING_PAPER_MODE at module-import time (backend/trading/config.py).
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.trading.config import BotConfig
from backend.trading.stream_ingestor import StreamIngestor
from backend.dashboard import register_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

config_path = os.path.join(os.path.dirname(__file__), "trading_config.yaml")
bot_config = BotConfig.from_yaml(config_path)
ingestor: Optional[StreamIngestor] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingestor
    logger.info("Meridian backend starting up")
    ingestor = StreamIngestor(bot_config)
    try:
        ingestor.start()
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
    title="Meridian Trading Bot",
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

register_dashboard(app)


@app.get("/")
def health():
    return {
        "service": "meridian",
        "version": "1.0.0",
        "bot_running": bool(ingestor and ingestor._running),
    }


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


@app.get("/api/trending")
def api_trending():
    if ingestor:
        return {"trending": ingestor.ticker_extractor.get_trending()}
    return {"trending": []}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
