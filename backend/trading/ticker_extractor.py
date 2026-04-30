from __future__ import annotations

import re
import time
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

CASHTAG_PATTERN = re.compile(r'\$([A-Z]{1,5})\b')
KNOWN_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V",
    "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "BAC", "XOM", "PFE",
    "KO", "PEP", "CSCO", "ABT", "CRM", "NFLX", "AMD", "INTC", "QCOM",
    "COST", "NKE", "MRK", "ORCL", "ACN", "LLY", "MCD", "SBUX", "GS",
    "AVGO", "NOW", "PANW", "PLTR", "COIN", "SQ", "SHOP", "ROKU", "SOFI",
    "GME", "AMC", "RIVN", "HOOD", "MARA", "RIOT", "MSTR", "SPY", "QQQ",
}
NOISE = {"A", "I", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT",
         "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE",
         "AI", "CEO", "IPO", "ETF", "GDP", "SEC", "FDA", "FED", "DD", "PM",
         "AM", "ALL", "ANY", "ARE", "BIG", "CAN", "DAY", "FOR", "HAS", "ITS",
         "NEW", "NOW", "OLD", "ONE", "OUR", "OUT", "OWN", "PUT", "TOP", "TWO"}


class TickerExtractor:
    def __init__(self):
        self._mentions: dict[str, list[float]] = defaultdict(list)
        self._window = 300

    def extract(self, text: str) -> list[str]:
        if not text:
            return []
        found = set()
        for match in CASHTAG_PATTERN.finditer(text):
            ticker = match.group(1)
            if ticker not in NOISE and len(ticker) >= 1:
                found.add(ticker)
        text_upper = text.upper()
        for t in KNOWN_TICKERS:
            if f" {t} " in f" {text_upper} " or text_upper.startswith(f"{t} ") or text_upper.endswith(f" {t}"):
                found.add(t)
        return list(found)

    def record_mention(self, ticker: str):
        now = time.time()
        self._mentions[ticker].append(now)
        cutoff = now - self._window
        self._mentions[ticker] = [t for t in self._mentions[ticker] if t > cutoff]

    def get_trending(self, min_mentions: int = 8) -> list[dict[str, Any]]:
        now = time.time()
        cutoff = now - self._window
        trending = []
        for ticker, times in self._mentions.items():
            recent = [t for t in times if t > cutoff]
            if len(recent) >= min_mentions:
                trending.append({
                    "ticker": ticker,
                    "mentions": len(recent),
                    "velocity": len(recent) / (self._window / 60),
                })
        trending.sort(key=lambda x: x["mentions"], reverse=True)
        return trending[:20]

    def cleanup(self):
        cutoff = time.time() - self._window * 2
        for ticker in list(self._mentions.keys()):
            self._mentions[ticker] = [t for t in self._mentions[ticker] if t > cutoff]
            if not self._mentions[ticker]:
                del self._mentions[ticker]
