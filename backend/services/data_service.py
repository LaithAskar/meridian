from __future__ import annotations

import logging
from typing import Any, Optional

import yfinance as yf
import pandas as pd
import numpy as np

from backend.utils.helpers import TTLCache, safe_float

logger = logging.getLogger(__name__)

POPULAR_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "BAC",
    "XOM", "PFE", "KO", "PEP", "CSCO", "ABT", "CRM", "NFLX", "AMD",
    "INTC", "QCOM", "COST", "T", "VZ", "NKE", "MRK", "TMO", "AVGO",
    "ORCL", "ACN", "LLY", "MCD", "TXN", "UPS", "LOW", "SBUX", "GS",
    "BLK", "AMAT", "ISRG", "GILD", "MDLZ", "ADP", "SYK", "BKNG",
    "LRCX", "VRTX", "REGN", "ZTS", "NOW", "PANW", "SNPS", "CDNS",
    "KLAC", "MRVL", "FTNT", "ADSK", "ABNB", "DDOG", "CRWD", "WDAY",
    "TEAM", "ZS", "MDB", "NET", "SNOW", "PLTR", "COIN", "SQ", "SHOP",
    "ROKU", "U", "RBLX", "HOOD", "SOFI", "RIVN", "LCID", "NIO",
    "XPEV", "LI", "MARA", "RIOT", "MSTR", "GME", "AMC", "BB",
    "BBBY", "SPCE", "OPEN", "WISH", "CLOV", "WKHS",
]


@TTLCache(ttl=60, maxsize=200)
def get_ticker_obj(ticker: str) -> yf.Ticker:
    return yf.Ticker(ticker.upper())


@TTLCache(ttl=30, maxsize=200)
def get_quote(ticker: str) -> dict[str, Any]:
    try:
        t = get_ticker_obj(ticker)
        info = t.info or {}
        price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        prev_close = safe_float(info.get("previousClose") or info.get("regularMarketPreviousClose"))
        change = price - prev_close if price and prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "ticker": ticker.upper(),
            "name": info.get("shortName") or info.get("longName") or ticker.upper(),
            "price": price,
            "previousClose": prev_close,
            "change": round(change, 2),
            "changePercent": round(change_pct, 2),
            "open": safe_float(info.get("open") or info.get("regularMarketOpen")),
            "high": safe_float(info.get("dayHigh") or info.get("regularMarketDayHigh")),
            "low": safe_float(info.get("dayLow") or info.get("regularMarketDayLow")),
            "volume": safe_int_vol(info.get("volume") or info.get("regularMarketVolume")),
            "avgVolume": safe_int_vol(info.get("averageVolume")),
            "marketCap": safe_float(info.get("marketCap")),
            "pe": safe_float(info.get("trailingPE")),
            "forwardPe": safe_float(info.get("forwardPE")),
            "eps": safe_float(info.get("trailingEps")),
            "beta": safe_float(info.get("beta")),
            "dividend": safe_float(info.get("dividendYield", 0)) * 100,
            "week52High": safe_float(info.get("fiftyTwoWeekHigh")),
            "week52Low": safe_float(info.get("fiftyTwoWeekLow")),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "exchange": info.get("exchange", "N/A"),
            "currency": info.get("currency", "USD"),
        }
    except Exception as e:
        logger.error(f"Quote error for {ticker}: {e}")
        return {"ticker": ticker.upper(), "name": ticker.upper(), "price": 0, "error": str(e)}


def safe_int_vol(val: Any) -> int:
    try:
        if val is None:
            return 0
        return int(float(val))
    except (ValueError, TypeError):
        return 0


@TTLCache(ttl=120, maxsize=100)
def get_history(ticker: str, period: str = "1y", interval: str = "1d") -> list[dict]:
    try:
        t = get_ticker_obj(ticker)
        df = t.history(period=period, interval=interval)
        if df is None or df.empty:
            return []
        df = df.reset_index()
        records = []
        for _, row in df.iterrows():
            date_val = row.get("Date") or row.get("Datetime")
            try:
                date_str = str(date_val)[:10] if date_val is not None else ""
            except Exception:
                date_str = ""
            records.append({
                "date": date_str,
                "open": safe_float(row.get("Open")),
                "high": safe_float(row.get("High")),
                "low": safe_float(row.get("Low")),
                "close": safe_float(row.get("Close")),
                "volume": safe_int_vol(row.get("Volume")),
            })
        return records
    except Exception as e:
        logger.error(f"History error for {ticker}: {e}")
        return []


@TTLCache(ttl=300, maxsize=100)
def get_info(ticker: str) -> dict[str, Any]:
    try:
        t = get_ticker_obj(ticker)
        return t.info or {}
    except Exception as e:
        logger.error(f"Info error for {ticker}: {e}")
        return {}


@TTLCache(ttl=300, maxsize=100)
def get_financials(ticker: str) -> dict[str, Any]:
    try:
        t = get_ticker_obj(ticker)
        result = {}
        for attr, key in [("income_stmt", "incomeStatement"), ("balance_sheet", "balanceSheet"), ("cashflow", "cashFlow")]:
            df = getattr(t, attr, None)
            if df is not None and not df.empty:
                result[key] = {str(col)[:10]: {str(idx): safe_float(val) for idx, val in df[col].items()} for col in df.columns}
            else:
                result[key] = {}
        return result
    except Exception as e:
        logger.error(f"Financials error for {ticker}: {e}")
        return {"incomeStatement": {}, "balanceSheet": {}, "cashFlow": {}}


@TTLCache(ttl=600, maxsize=100)
def get_earnings(ticker: str) -> list[dict]:
    try:
        t = get_ticker_obj(ticker)
        earnings = t.earnings_history
        if earnings is not None and not earnings.empty:
            records = []
            for _, row in earnings.iterrows():
                records.append({
                    "date": str(row.get("Earnings Date", ""))[:10],
                    "epsEstimate": safe_float(row.get("EPS Estimate")),
                    "epsActual": safe_float(row.get("Reported EPS")),
                    "surprise": safe_float(row.get("Surprise(%)")),
                })
            return records[-20:]
        # Fallback: quarterly earnings
        qe = t.quarterly_earnings
        if qe is not None and not qe.empty:
            records = []
            for idx, row in qe.iterrows():
                records.append({
                    "date": str(idx),
                    "epsEstimate": safe_float(row.get("Estimated")),
                    "epsActual": safe_float(row.get("Actual")),
                    "surprise": safe_float(row.get("Surprise")),
                })
            return records[-20:]
        return []
    except Exception as e:
        logger.error(f"Earnings error for {ticker}: {e}")
        return []


def search_tickers(query: str) -> list[dict]:
    query_upper = query.upper().strip()
    results = []
    for t in POPULAR_TICKERS:
        if query_upper in t:
            results.append({"ticker": t, "name": t})
    if not results:
        try:
            ticker = yf.Ticker(query_upper)
            info = ticker.info or {}
            if info.get("shortName"):
                results.append({"ticker": query_upper, "name": info.get("shortName", query_upper)})
        except Exception:
            pass
    return results[:10]


@TTLCache(ttl=300, maxsize=50)
def get_analyst_info(ticker: str) -> dict[str, Any]:
    try:
        t = get_ticker_obj(ticker)
        info = t.info or {}
        rec = info.get("recommendationKey", "none")
        target_mean = safe_float(info.get("targetMeanPrice"))
        target_high = safe_float(info.get("targetHighPrice"))
        target_low = safe_float(info.get("targetLowPrice"))
        num = safe_int_vol(info.get("numberOfAnalystOpinions"))
        return {
            "recommendation": rec,
            "targetMean": target_mean,
            "targetHigh": target_high,
            "targetLow": target_low,
            "numberOfAnalysts": num,
            "currentPrice": safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        }
    except Exception as e:
        logger.error(f"Analyst error for {ticker}: {e}")
        return {"recommendation": "none", "targetMean": 0, "numberOfAnalysts": 0}
