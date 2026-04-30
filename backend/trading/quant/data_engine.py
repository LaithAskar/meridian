from __future__ import annotations

import logging
from typing import Any

import yfinance as yf
import pandas as pd
import numpy as np

from backend.utils.helpers import TTLCache, safe_float

logger = logging.getLogger(__name__)

QUANT_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM",
    "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "BAC", "XOM",
    "KO", "PEP", "CRM", "NFLX", "AMD", "INTC", "COST", "NKE",
    "ORCL", "LLY", "MCD", "AVGO", "GS",
]


@TTLCache(ttl=300, maxsize=5)
def fetch_universe_data(period: str = "6mo") -> dict[str, pd.DataFrame]:
    data = {}
    try:
        download = yf.download(QUANT_UNIVERSE, period=period, interval="1d", progress=False, group_by="ticker")
        if download is None or download.empty:
            return {}
        for ticker in QUANT_UNIVERSE:
            try:
                if ticker in download.columns.get_level_values(0):
                    df = download[ticker].dropna()
                    if len(df) >= 50:
                        data[ticker] = df
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Universe data fetch error: {e}")
        # Fallback: fetch individually
        for ticker in QUANT_UNIVERSE[:15]:
            try:
                t = yf.Ticker(ticker)
                df = t.history(period=period, interval="1d")
                if df is not None and len(df) >= 50:
                    data[ticker] = df
            except Exception:
                continue
    return data


def get_fundamentals(ticker: str) -> dict[str, float]:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        return {
            "pe": safe_float(info.get("trailingPE")),
            "pb": safe_float(info.get("priceToBook")),
            "roe": safe_float(info.get("returnOnEquity", 0)) * 100,
            "margin": safe_float(info.get("profitMargins", 0)) * 100,
            "beta": safe_float(info.get("beta")),
            "marketCap": safe_float(info.get("marketCap")),
            "dividendYield": safe_float(info.get("dividendYield", 0)) * 100,
        }
    except Exception:
        return {"pe": 0, "pb": 0, "roe": 0, "margin": 0, "beta": 0, "marketCap": 0, "dividendYield": 0}
