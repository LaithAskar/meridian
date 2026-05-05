from __future__ import annotations

import asyncio
import time
import logging
import threading
from datetime import datetime
from typing import Any, Optional

from backend.trading.config import BotConfig
from backend.trading.sentiment_engine import SentimentEngine
from backend.trading.ticker_extractor import TickerExtractor
from backend.trading.trade_executor import TradeExecutor
from backend.trading.signal_bus import SignalBus
from backend.trading.adaptive import AdaptiveLearner
from backend.trading.sources.finviz_source import FinvizSource
from backend.trading.sources.yfinance_source import YFinanceSource
from backend.trading.sources.reddit_source import RedditSource
from backend.trading.sources.stocktwits_source import StockTwitsSource
from backend.trading.quant.data_engine import fetch_universe_data
from backend.trading.quant.momentum import momentum_signals
from backend.trading.quant.mean_reversion import mean_reversion_signals
from backend.trading.quant.factor_model import factor_signals
from backend.trading.quant.regime_detector import detect_regime
from backend.trading.quant.signal_aggregator import aggregate_signals
from backend.trading.quant.risk_manager import QuantRiskManager
from backend.trading.quant.pdt_guard import PDTGuard
from backend.trading.quant.adaptive_quant import AdaptiveQuant
from backend.utils.helpers import safe_float, clamp

logger = logging.getLogger(__name__)


def is_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hour = now.hour
    minute = now.minute
    if hour < 9 or (hour == 9 and minute < 30):
        return False
    if hour >= 16:
        return False
    return True


def is_tradeable_window(blackout_min: int) -> bool:
    """Market open AND past the open-blackout window. Blackout suppresses
    stale-headline blast at open by skipping the first N minutes."""
    if not is_market_hours():
        return False
    if blackout_min <= 0:
        return True
    now = datetime.now()
    if now.hour == 9 and now.minute < 30 + blackout_min:
        return False
    return True


class StreamIngestor:
    def __init__(self, config: BotConfig):
        self.config = config
        self.sentiment_engine = SentimentEngine(config.sentiment.vader_threshold)
        self.ticker_extractor = TickerExtractor()
        self.executor = TradeExecutor(
            paper_mode=config.trading.paper_mode,
            liquidity_reserve_pct=config.trading.liquidity_reserve_pct,
            max_daily_trades=config.trading.max_daily_trades,
            max_daily_loss_pct=config.trading.max_daily_loss_pct,
        )
        self.signal_bus = SignalBus()
        self.adaptive = AdaptiveLearner()
        self.adaptive_quant = AdaptiveQuant()
        self.risk_manager = QuantRiskManager(max_position_pct=config.trading.max_position_pct)
        self.pdt_guard = PDTGuard(self.executor.pdt)

        # Sources
        self.finviz = FinvizSource()
        self.yfinance_src = YFinanceSource()
        reddit_cfg = config.sources.get("reddit")
        self.reddit = RedditSource(
            subreddits=reddit_cfg.subreddits if reddit_cfg else ["wallstreetbets", "stocks"],
            min_score=reddit_cfg.min_score if reddit_cfg else 3,
        )
        self.stocktwits = StockTwitsSource()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_quant_run = 0.0
        self._quant_interval = config.quant.cycle_minutes * 60
        self._ws_clients: list[Any] = []
        self._start_time: Optional[float] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self.executor.login()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("StreamIngestor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("StreamIngestor stopped")

    def _run_loop(self):
        while self._running:
            try:
                if is_tradeable_window(self.config.trading.open_blackout_minutes):
                    self._sentiment_cycle()
                    now = time.time()
                    if now - self._last_quant_run >= self._quant_interval:
                        self._quant_cycle()
                        self._last_quant_run = now
                elif is_market_hours():
                    logger.debug(f"In open blackout (first {self.config.trading.open_blackout_minutes}min), skipping cycle")
                else:
                    logger.debug("Market closed, sleeping 60s")
                cycle_sleep = 30 + (60 * (0 if is_market_hours() else 1))
                for _ in range(int(cycle_sleep)):
                    if not self._running:
                        return
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Ingestor loop error: {e}")
                time.sleep(10)

    def _sentiment_cycle(self):
        try:
            # Fetch headlines
            finviz_news = self.finviz.fetch_headlines()
            yf_news = self.yfinance_src.fetch_headlines()
            all_headlines = finviz_news + yf_news

            # Optional sources
            try:
                reddit_posts = self.reddit.fetch_headlines()
                all_headlines.extend([{"title": p["title"], "source": "reddit", "ticker": ""} for p in reddit_posts])
            except Exception:
                pass

            # Analyze sentiment
            for item in all_headlines:
                tickers = item.get("ticker", "")
                if isinstance(tickers, str) and tickers:
                    tickers = [tickers]
                elif isinstance(tickers, list):
                    pass
                else:
                    tickers = self.ticker_extractor.extract(item.get("title", ""))

                sentiment = self.sentiment_engine.analyze(item.get("title", ""))
                if not sentiment["passed"]:
                    continue

                source = item.get("source", "unknown")
                source_weight = self.adaptive.get_source_weight(source)

                for ticker in tickers:
                    if not ticker:
                        continue
                    self.ticker_extractor.record_mention(ticker)
                    direction = sentiment["label"]

                    signal = {
                        "ticker": ticker,
                        "direction": direction,
                        "compound": sentiment["compound"],
                        "source": source,
                        "title": item.get("title", "")[:100],
                        "sourceWeight": source_weight,
                        "engine": "sentiment",
                    }
                    self.signal_bus.emit_signal(signal)
                    self._broadcast_signal(signal)

                    # Check if should trade
                    trade_check = self.signal_bus.should_trade(ticker, direction)
                    if trade_check["trade"]:
                        self._execute_sentiment_trade(ticker, direction, sentiment["compound"], source)

        except Exception as e:
            logger.error(f"Sentiment cycle error: {e}")

    def _execute_sentiment_trade(self, ticker: str, direction: str, compound: float, source: str):
        buying_power = self.executor.get_buying_power()
        equity = self.executor.get_equity()
        if buying_power < 5:
            return

        sizing_mult = self.adaptive.get_sizing_multiplier()
        conviction = min(abs(compound), 1.0)
        base_pct = 0.06 + conviction * 0.09  # 6-15% of available capital
        dollars = buying_power * base_pct * sizing_mult
        dollars = clamp(dollars, self.config.trading.min_trade_dollars, self.config.trading.max_trade_dollars)

        intent = {
            "ticker": ticker,
            "direction": direction,
            "dollars": round(dollars, 2),
            "compound": compound,
            "source": source,
            "engine": "sentiment",
        }
        self.signal_bus.emit_intent(intent)

        if direction == "bullish":
            result = self.executor.execute_buy(ticker, dollars, f"Sentiment buy: {compound:.2f} from {source}")
        elif direction == "bearish":
            if not self.signal_bus.positions.get_position(ticker):
                logger.info(f"SKIP sentiment sell {ticker}: no open position (would be naked short)")
                return
            result = self.executor.execute_sell(ticker, dollars, f"Sentiment sell: {compound:.2f} from {source}")
        else:
            return

        if result:
            self.signal_bus.positions.update(ticker, "buy" if direction == "bullish" else "sell", dollars)

    def _quant_cycle(self):
        try:
            logger.info("Running quant engine cycle")
            universe = fetch_universe_data()
            if not universe:
                return

            regime = detect_regime()
            weights = self.adaptive_quant.get_weights()
            # Override with regime weights if available
            regime_weights = regime.get("strategyWeights", {})
            if regime_weights:
                for k in weights:
                    if k in regime_weights:
                        weights[k] = (weights[k] + regime_weights[k]) / 2

            mom = momentum_signals(universe)
            rev = mean_reversion_signals(universe)
            fac = factor_signals(universe)

            aggregated = aggregate_signals(mom, rev, fac, weights, self.config.quant.min_consensus)
            equity = self.executor.get_equity()
            filtered = self.pdt_guard.filter_signals(aggregated, equity)

            for sig in filtered[:5]:
                signal = {**sig, "engine": "quant"}
                self.signal_bus.emit_signal(signal)
                self._broadcast_signal(signal)

                buying_power = self.executor.get_buying_power()
                dollars = self.risk_manager.size_trade(sig, equity, buying_power)
                dollars *= self.adaptive_quant.sizing_multiplier
                dollars = clamp(dollars, self.config.trading.min_trade_dollars, self.config.trading.max_trade_dollars)

                validation = self.risk_manager.validate_trade(sig, self.signal_bus.positions.get_all(), equity)
                if not validation["allowed"]:
                    continue

                intent = {**sig, "dollars": round(dollars, 2), "engine": "quant"}
                self.signal_bus.emit_intent(intent)

                if sig["direction"] == "buy":
                    result = self.executor.execute_buy(sig["ticker"], dollars, f"Quant buy: score={sig['ensembleScore']:.3f}")
                    if result:
                        self.signal_bus.positions.update(sig["ticker"], "buy", dollars)
                elif sig["direction"] == "sell":
                    if not self.signal_bus.positions.get_position(sig["ticker"]):
                        logger.info(f"SKIP quant sell {sig['ticker']}: no open position (would be naked short)")
                        continue
                    result = self.executor.execute_sell(sig["ticker"], dollars, f"Quant sell: score={sig['ensembleScore']:.3f}")
                    if result:
                        self.signal_bus.positions.update(sig["ticker"], "sell", dollars)

            logger.info(f"Quant cycle: {len(aggregated)} signals, {len(filtered)} after PDT filter, regime={regime.get('regime')}")
        except Exception as e:
            logger.error(f"Quant cycle error: {e}")

    def _broadcast_signal(self, signal: dict):
        for client in list(self._ws_clients):
            try:
                import json
                asyncio.get_event_loop().call_soon_threadsafe(
                    client.send_json, signal
                )
            except Exception:
                self._ws_clients.remove(client)

    def get_status(self) -> dict[str, Any]:
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "uptime": round(uptime),
            "marketOpen": is_market_hours(),
            "stats": self.executor.get_stats(),
            "recentTrades": self.executor.get_trade_log(20),
            "trending": self.ticker_extractor.get_trending(self.config.trending.min_mentions),
            "adaptiveSentiment": self.adaptive.get_stats(),
            "adaptiveQuant": self.adaptive_quant.get_stats(),
            "paperMode": self.config.trading.paper_mode,
            "loggedIn": self.executor.is_logged_in,
        }

    def get_signals(self) -> dict[str, Any]:
        return {
            "signals": self.signal_bus.get_recent_signals(50),
            "intents": self.signal_bus.get_recent_intents(20),
        }
