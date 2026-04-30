from __future__ import annotations

import logging
import time
from typing import Any

import requests
from lxml import html

logger = logging.getLogger(__name__)

FINVIZ_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM",
    "AMD", "NFLX", "CRM", "COIN", "SQ", "PLTR", "RIVN", "SOFI",
    "GME", "AMC", "MARA", "RIOT", "NIO", "SHOP", "ROKU", "HOOD",
]


class FinvizSource:
    def __init__(self):
        self._last_fetch: dict[str, float] = {}
        self._cache: dict[str, list[dict]] = {}
        self._min_interval = 30

    def fetch_headlines(self, tickers: list[str] | None = None) -> list[dict[str, Any]]:
        tickers = tickers or FINVIZ_TICKERS
        all_headlines = []
        for ticker in tickers:
            now = time.time()
            last = self._last_fetch.get(ticker, 0)
            if now - last < self._min_interval and ticker in self._cache:
                all_headlines.extend(self._cache[ticker])
                continue
            try:
                url = f"https://finviz.com/quote.ashx?t={ticker}"
                headers = {
                    "User-Agent": "meridian/1.0",
                    "Accept": "text/html",
                }
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue
                tree = html.fromstring(resp.content)
                news_table = tree.xpath('//table[@id="news-table"]')
                if not news_table:
                    continue
                rows = news_table[0].xpath('.//tr')
                headlines = []
                current_date = ""
                for row in rows[:15]:
                    cells = row.xpath('.//td')
                    if len(cells) >= 2:
                        date_cell = cells[0].text_content().strip()
                        if len(date_cell) > 10:
                            parts = date_cell.split()
                            if len(parts) >= 2:
                                current_date = parts[0]
                                time_str = parts[1] if len(parts) > 1 else ""
                            else:
                                time_str = date_cell
                        else:
                            time_str = date_cell
                        link = cells[1].xpath('.//a')
                        if link:
                            title = link[0].text_content().strip()
                            href = link[0].get("href", "")
                            if title:
                                headlines.append({
                                    "ticker": ticker,
                                    "title": title,
                                    "url": href,
                                    "source": "finviz",
                                    "date": current_date,
                                    "time": time_str,
                                })
                self._cache[ticker] = headlines
                self._last_fetch[ticker] = now
                all_headlines.extend(headlines)
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"Finviz fetch error for {ticker}: {e}")
                continue
        return all_headlines
