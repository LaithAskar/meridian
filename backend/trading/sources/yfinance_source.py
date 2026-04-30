from __future__ import annotations

import logging
import time
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

YFINANCE_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "AMD", "NFLX", "CRM", "COIN", "PLTR", "SOFI", "GME",
    "RIVN", "HOOD", "MARA", "NIO", "SHOP",
]


class YFinanceSource:
    def __init__(self):
        self._last_fetch: dict[str, float] = {}
        self._cache: dict[str, list[dict]] = {}
        self._min_interval = 60

    def fetch_headlines(self, tickers: list[str] | None = None) -> list[dict[str, Any]]:
        tickers = tickers or YFINANCE_TICKERS
        all_headlines = []
        for ticker in tickers:
            now = time.time()
            last = self._last_fetch.get(ticker, 0)
            if now - last < self._min_interval and ticker in self._cache:
                all_headlines.extend(self._cache[ticker])
                continue
            try:
                t = yf.Ticker(ticker)
                news = t.news or []
                headlines = []
                for item in news[:10]:
                    content = item.get("content", item)
                    if isinstance(content, dict):
                        title = content.get("title", "")
                        summary = content.get("summary", "")
                        pub_date = content.get("pubDate", "")
                        provider = content.get("provider", {})
                        source_name = provider.get("displayName", "") if isinstance(provider, dict) else str(provider)
                        canonical = content.get("canonicalUrl", {})
                        url = canonical.get("url", "") if isinstance(canonical, dict) else ""
                    else:
                        title = item.get("title", "")
                        summary = item.get("summary", "")
                        pub_date = item.get("providerPublishTime", "")
                        source_name = item.get("publisher", "")
                        url = item.get("link", "")
                    if title:
                        headlines.append({
                            "ticker": ticker,
                            "title": title,
                            "summary": summary[:200] if summary else "",
                            "url": url,
                            "source": "yfinance",
                            "publisher": source_name,
                            "date": str(pub_date),
                        })
                self._cache[ticker] = headlines
                self._last_fetch[ticker] = now
                all_headlines.extend(headlines)
            except Exception as e:
                logger.debug(f"YFinance news error for {ticker}: {e}")
                continue
        return all_headlines
