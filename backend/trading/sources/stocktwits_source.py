from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class StockTwitsSource:
    def __init__(self, trending_only: bool = False):
        self.trending_only = trending_only
        self._last_fetch = 0.0
        self._cache: list[dict] = []
        self._min_interval = 120

    def fetch_headlines(self, tickers: list[str] | None = None) -> list[dict[str, Any]]:
        now = time.time()
        if now - self._last_fetch < self._min_interval and self._cache:
            return self._cache
        results = []
        try:
            if self.trending_only:
                url = "https://api.stocktwits.com/api/2/trending/symbols.json"
            else:
                url = "https://api.stocktwits.com/api/2/streams/trending.json"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "meridian/1.0"})
            if resp.status_code == 403:
                logger.debug("StockTwits 403 (cloud IP blocked)")
                return []
            if resp.status_code != 200:
                return []
            data = resp.json()
            for msg in data.get("messages", [])[:20]:
                body = msg.get("body", "")
                if body:
                    symbols = [s.get("symbol", "") for s in msg.get("symbols", [])]
                    results.append({
                        "title": body[:200],
                        "source": "stocktwits",
                        "tickers": symbols,
                        "sentiment": msg.get("entities", {}).get("sentiment", {}).get("basic", ""),
                        "date": msg.get("created_at", ""),
                    })
        except Exception as e:
            logger.debug(f"StockTwits error: {e}")
        self._cache = results
        self._last_fetch = now
        return results
