"""
yfinance daily bar fetcher with parquet cache.

No API credentials required — yfinance pulls Yahoo Finance data directly.

Design notes
------------
* Per-symbol download + cache: each symbol is stored as a separate parquet
  file at data/cache/{symbol}_{interval}.parquet.  Per-symbol caching keeps
  individual files small (~3 500 rows for 14 years of daily data) and allows
  partial cache hits when only some symbols need refreshing.

* Rate limiting: yfinance uses an unofficial Yahoo Finance API.  We serialize
  downloads (threads=False) and pause ~0.2 s between fetches (~5 symbols/sec)
  to stay within Yahoo's informal rate limit.  A single retry is attempted
  when yf.download returns an empty DataFrame (the most common symptom of a
  transient rate-limit rejection).

* Column normalization: yfinance ≥ 1.x returns MultiIndex columns
  (Price, Ticker) even for single-symbol downloads.  We flatten to the Price
  level and lowercase to produce the uniform (open, high, low, close, volume)
  interface that the rest of the backtester expects.

* auto_adjust=True gives total-return semantics (splits + dividends baked
  into OHLC prices) as required by DESIGN.md.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "cache"

_YF_RATE_LIMIT_PAUSE = 0.2  # seconds between fetches (~5 symbols/sec)
_YF_RETRY_PAUSE = 1.0       # seconds before the single retry attempt

# Calendar-day slack allowed at the edges of a cached date range.  yfinance
# only returns trading days, so a request starting on a Saturday is satisfied
# by a cache that starts on the following Monday.  The longest US-market
# holiday-weekend gap is 4 days (e.g., Thanksgiving Thursday + Friday close);
# 7 covers it plus a small safety margin.  Without this slack a bug would
# silently truncate the cache to the requested window on every misaligned
# call — found 2026-05-17 after a backtest re-fetched 2010-2024 data down
# to 2010-2023 because the request started on 2010-01-01 (Saturday) and the
# existing cache started on 2010-01-04 (Monday, first trading day of 2010).
_CACHE_DATE_TOLERANCE_DAYS = 7


def _cache_path(symbol: str, interval: str) -> Path:
    return _CACHE_DIR / f"{symbol}_{interval}.parquet"


def _cache_covers(path: Path, start: date, end: date) -> bool:
    """Return True if *path* exists and its trading-day index spans
    approximately [start, end].

    "Approximately" tolerates up to _CACHE_DATE_TOLERANCE_DAYS calendar days
    of slack at each edge to account for non-trading-day start/end requests
    being satisfied by a cache whose first/last dates are the nearest trading
    days.
    """
    if not path.exists():
        return False
    df = pd.read_parquet(path)
    if df.empty:
        return False

    idx = df.index
    dates = idx.get_level_values("date") if isinstance(idx, pd.MultiIndex) else idx

    first: date = pd.Timestamp(dates.min()).date()
    last: date = pd.Timestamp(dates.max()).date()
    start_ok = (first - start).days <= _CACHE_DATE_TOLERANCE_DAYS
    end_ok = (end - last).days <= _CACHE_DATE_TOLERANCE_DAYS
    return start_ok and end_ok


def _download_symbol(symbol: str, start: date, end: date, interval: str) -> pd.DataFrame:
    """
    Call yf.download for one symbol and return a tz-naive DatetimeIndex DataFrame
    with lowercase columns open/high/low/close/volume.

    Retries once on an empty result (common symptom of a transient rate limit).
    """
    # yfinance end date is exclusive
    end_str = (end + timedelta(days=1)).isoformat()

    def _fetch() -> pd.DataFrame:
        return yf.download(
            symbol,
            start=start.isoformat(),
            end=end_str,
            interval=interval,
            auto_adjust=True,
            threads=False,
            progress=False,
        )

    raw = _fetch()
    if raw.empty:
        time.sleep(_YF_RETRY_PAUSE)
        raw = _fetch()

    if raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    # yfinance >= 1.x: columns are a (Price, Ticker) MultiIndex — flatten to Price
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.rename(columns=str.lower)

    # Keep only OHLCV; ignore adj_close, dividends, stock_splits, etc.
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in raw.columns]
    raw = raw[keep].copy()

    # Ensure tz-naive DatetimeIndex named "date"
    if hasattr(raw.index, "tz") and raw.index.tz is not None:
        raw.index = raw.index.tz_localize(None)
    raw.index.name = "date"

    return raw


def fetch_bars(
    symbols: list[str],
    start: date,
    end: date,
    interval: str = "1d",
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Return daily OHLCV bars for *symbols* over the inclusive window [start, end].

    Returns
    -------
    pd.DataFrame with a MultiIndex of (symbol, date) and columns:
        open, high, low, close, volume

    Caching
    -------
    Each symbol is cached independently at
    ``data/cache/{symbol}_{interval}.parquet``.

    Cache hit: file exists and its date range covers [start, end].  The symbol
    is read from disk without any network call.

    Cache miss: symbol is fetched from Yahoo Finance, written to disk, then
    used.  Fetches are paced at ~5 symbols/sec to stay within rate limits.

    The returned DataFrame is always filtered to exactly [start, end] so that
    a wide-range cache serving a narrow request does not leak extra rows.

    Parameters
    ----------
    symbols   : ticker strings (uppercase)
    start     : inclusive start date
    end       : inclusive end date
    interval  : yfinance interval string (default '1d' for daily)
    cache_dir : override cache directory (used in tests)
    """
    if not symbols:
        return pd.DataFrame()

    effective_cache = cache_dir if cache_dir is not None else _CACHE_DIR
    effective_cache.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    fetched_count = 0

    for sym in symbols:
        path = effective_cache / f"{sym}_{interval}.parquet"

        if _cache_covers(path, start, end):
            df_sym = pd.read_parquet(path)
        else:
            # Pace API calls; skip the pause before the very first fetch
            if fetched_count > 0:
                time.sleep(_YF_RATE_LIMIT_PAUSE)
            df_sym = _download_symbol(sym, start, end, interval)
            fetched_count += 1
            if not df_sym.empty:
                df_sym.to_parquet(path)

        if df_sym.empty:
            continue

        # Guard: cached files should have a plain DatetimeIndex; skip if malformed
        if isinstance(df_sym.index, pd.MultiIndex):
            continue

        df_sym.index.name = "date"

        # Promote to (symbol, date) MultiIndex
        df_sym = df_sym.copy()
        df_sym.index = pd.MultiIndex.from_tuples(
            [(sym, d) for d in df_sym.index],
            names=["symbol", "date"],
        )
        frames.append(df_sym)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames).sort_index()

    # Filter to the exact requested window (cache may span a wider range)
    date_level = result.index.get_level_values("date")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    mask = (date_level >= start_ts) & (date_level <= end_ts)
    result = result.loc[mask]

    return result
