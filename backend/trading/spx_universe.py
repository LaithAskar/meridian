"""S&P 500 universe membership.

Source of truth for whether a ticker is a current SPX constituent. Used to
gate trading decisions (sentiment + quant) so the bot doesn't trade meme
stocks where signals are noise.

Fetches from Wikipedia (free, no API key) and caches to disk. Falls back
to a static list of liquid SPX names if Wikipedia is unreachable.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Minimal static fallback — most liquid SPX names. Used only if Wikipedia
# fetch fails AND no cache file exists. Refresh by running the fetch.
_FALLBACK_SPX = frozenset({
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO",
    "BRK-B", "LLY", "JPM", "V", "WMT", "XOM", "UNH", "MA", "JNJ", "PG", "HD",
    "ORCL", "COST", "ABBV", "BAC", "CVX", "CRM", "KO", "MRK", "PEP", "NFLX",
    "AMD", "TMO", "ADBE", "WFC", "MCD", "CSCO", "ACN", "ABT", "LIN", "PM",
    "TXN", "GE", "CAT", "QCOM", "DIS", "GS", "VZ", "INTU", "DHR", "AXP",
    "PFE", "INTC", "T", "MS", "BLK", "AMGN", "CMCSA", "RTX", "BKNG", "C",
    "NEE", "AMAT", "PGR", "ISRG", "SPGI", "TJX", "LOW", "MDT", "UBER", "VRTX",
    "ETN", "SCHW", "BSX", "BA", "DE", "ELV", "ADP", "BMY", "REGN", "GILD",
    "MMC", "ADI", "TMUS", "SBUX", "CB", "LMT", "NKE", "MU", "PLTR", "MO",
    "FISV", "SYK", "BX", "MDLZ", "PANW", "AMT", "DUK", "SHW", "TGT", "CI",
})

_CACHE_FILE = os.path.expanduser("~/.meridian_spx_constituents.json")
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # weekly refresh
_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

_cached: Optional[frozenset[str]] = None


def _read_cache() -> Optional[frozenset[str]]:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        st = os.stat(_CACHE_FILE)
        if time.time() - st.st_mtime > _CACHE_TTL_SECONDS:
            return None
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        tickers = data.get("tickers", [])
        if not isinstance(tickers, list) or not tickers:
            return None
        return frozenset(tickers)
    except Exception as e:
        logger.warning(f"SPX cache read failed: {e}")
        return None


def _write_cache(tickers: frozenset[str]) -> None:
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump({"tickers": sorted(tickers), "fetched_at": time.time()}, f)
    except Exception as e:
        logger.warning(f"SPX cache write failed: {e}")


def _fetch_from_wikipedia() -> Optional[frozenset[str]]:
    try:
        import requests
        # Wikipedia rejects default urllib User-Agent with 403 — fetch HTML
        # ourselves and let pandas parse it
        resp = requests.get(_WIKI_URL, headers={"User-Agent": "Mozilla/5.0 meridian-bot"}, timeout=10)
        resp.raise_for_status()
        from io import StringIO
        tables = pd.read_html(StringIO(resp.text))
        if not tables:
            return None
        df = tables[0]
        col = "Symbol" if "Symbol" in df.columns else df.columns[0]
        tickers = {str(t).replace(".", "-").strip() for t in df[col] if pd.notna(t)}
        # Sanity check — should have ~500 entries
        if len(tickers) < 400 or len(tickers) > 600:
            logger.warning(f"SPX wiki returned {len(tickers)} tickers, suspicious — using fallback")
            return None
        return frozenset(tickers)
    except Exception as e:
        logger.warning(f"SPX wiki fetch failed: {e}")
        return None


def get_spx_tickers() -> frozenset[str]:
    """Returns current SPX constituent set. Cached weekly."""
    global _cached
    if _cached is not None:
        return _cached

    cached = _read_cache()
    if cached is not None:
        _cached = cached
        logger.info(f"SPX universe loaded from cache: {len(cached)} tickers")
        return _cached

    fresh = _fetch_from_wikipedia()
    if fresh is not None:
        _write_cache(fresh)
        _cached = fresh
        logger.info(f"SPX universe fetched from Wikipedia: {len(fresh)} tickers")
        return _cached

    _cached = _FALLBACK_SPX
    logger.warning(f"SPX universe using static fallback: {len(_FALLBACK_SPX)} tickers")
    return _cached


def is_spx_member(ticker: str) -> bool:
    if not ticker:
        return False
    return ticker.upper() in get_spx_tickers()
