"""
Alpaca historical bar fetcher with parquet cache.

Credentials are read from environment variables:
    ALPACA_API_KEY    — Alpaca key ID
    ALPACA_SECRET_KEY — Alpaca secret key

Both variables must be set for live API calls.  Tests should monkeypatch
`_make_client` or the `StockHistoricalDataClient` constructor to avoid
requiring real credentials.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

# Root of the repo: two levels up from this file (backtest/data.py → repo root)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "cache"

# Alpaca timeframe strings that map to alpaca-py TimeFrame objects.
_TIMEFRAME_MAP: dict[str, object] = {}  # populated lazily to avoid import-time cost


def _get_timeframe(name: str) -> object:
    """Return an alpaca-py TimeFrame for a string like '1Hour'."""
    if not _TIMEFRAME_MAP:
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # noqa: PLC0415

        _TIMEFRAME_MAP.update(
            {
                "1Hour": TimeFrame.Hour,
                "1Day": TimeFrame.Day,
                "1Min": TimeFrame.Minute,
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
                "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            }
        )
    if name not in _TIMEFRAME_MAP:
        raise ValueError(f"Unsupported timeframe '{name}'. Supported: {list(_TIMEFRAME_MAP)}")
    return _TIMEFRAME_MAP[name]


def _make_client() -> object:
    """Construct a StockHistoricalDataClient from env vars."""
    from alpaca.data import StockHistoricalDataClient  # noqa: PLC0415

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise EnvironmentError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set to fetch live data."
        )
    return StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)


def _cache_path(symbol: str, timeframe: str) -> Path:
    return _CACHE_DIR / f"{symbol}_{timeframe}.parquet"


def _cache_covers(path: Path, start: date, end: date) -> bool:
    """
    Return True when the parquet file exists and its timestamp index spans
    at least [start, end] (inclusive on both ends).

    We only check the extremes stored in the file — no gap detection.  For
    the backtester's purpose (daily-bar completeness isn't critical; we just
    want to avoid re-downloading the same multi-year window), this is
    sufficient and fast (no full read required).
    """
    if not path.exists():
        return False
    df = pd.read_parquet(path)
    if df.empty:
        return False

    idx = df.index
    # Index may be MultiIndex (symbol, timestamp) or plain DatetimeIndex.
    if isinstance(idx, pd.MultiIndex):
        timestamps = idx.get_level_values("timestamp")
    else:
        timestamps = idx

    # Normalise to tz-naive dates for comparison
    first: date = pd.Timestamp(timestamps.min()).date()
    last: date = pd.Timestamp(timestamps.max()).date()
    return first <= start and last >= end


def _fetch_from_api(
    symbols: list[str],
    start: date,
    end: date,
    timeframe: str,
    client: Optional[object] = None,
) -> pd.DataFrame:
    """Call the Alpaca API and return a (symbol, timestamp) multi-index DataFrame."""
    from alpaca.data.enums import DataFeed  # noqa: PLC0415
    from alpaca.data.requests import StockBarsRequest  # noqa: PLC0415

    if client is None:
        client = _make_client()

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        start=datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        end=datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc),
        timeframe=_get_timeframe(timeframe),
        feed=DataFeed.IEX,
    )
    bar_set = client.get_stock_bars(request)
    df: pd.DataFrame = bar_set.df

    # Ensure the index levels are named consistently.
    if isinstance(df.index, pd.MultiIndex):
        df.index.names = ["symbol", "timestamp"]
    return df


def fetch_bars(
    symbols: list[str],
    start: date,
    end: date,
    timeframe: str = "1Hour",
    cache_dir: Optional[Path] = None,
    client: Optional[object] = None,
) -> pd.DataFrame:
    """
    Return hourly OHLCV bars for *symbols* over [start, end].

    Return value
    ------------
    pd.DataFrame with a MultiIndex of (symbol, timestamp) and columns:
        open, high, low, close, volume, trade_count, vwap

    Caching
    -------
    Each symbol is cached independently at
    ``data/cache/{symbol}_{timeframe}.parquet``.  On the first call the data
    is fetched from Alpaca and written to disk.  Subsequent calls that request
    a date range fully covered by the cached file skip the API entirely.

    If the cache does not cover the full requested range the symbol is
    re-fetched in full and the cache file is replaced.  (Merging partial
    ranges would complicate the code for negligible benefit — the bulk
    download script fetches the full 9-year window once.)

    Parameters
    ----------
    symbols   : list of ticker strings (uppercase)
    start     : inclusive start date
    end       : inclusive end date
    timeframe : alpaca-py timeframe name; default '1Hour'
    cache_dir : override cache directory (used in tests)
    client    : pre-constructed StockHistoricalDataClient (used in tests)
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    effective_cache = cache_dir if cache_dir is not None else _CACHE_DIR

    cached_frames: list[pd.DataFrame] = []
    symbols_to_fetch: list[str] = []

    for sym in symbols:
        path = effective_cache / f"{sym}_{timeframe}.parquet"
        if _cache_covers(path, start, end):
            df = pd.read_parquet(path)
            df.index.names = ["symbol", "timestamp"]
            cached_frames.append(df)
        else:
            symbols_to_fetch.append(sym)

    fetched_frames: list[pd.DataFrame] = []
    if symbols_to_fetch:
        df_all = _fetch_from_api(symbols_to_fetch, start, end, timeframe, client=client)
        # Split back per symbol and write individual cache files.
        for sym in symbols_to_fetch:
            if sym in df_all.index.get_level_values("symbol"):
                df_sym = df_all.xs(sym, level="symbol")
                df_sym = df_sym.copy()
                df_sym.index = pd.MultiIndex.from_tuples(
                    [(sym, ts) for ts in df_sym.index], names=["symbol", "timestamp"]
                )
                path = effective_cache / f"{sym}_{timeframe}.parquet"
                df_sym.to_parquet(path)
            else:
                df_sym = pd.DataFrame()
            fetched_frames.append(df_sym)

    all_frames = cached_frames + [f for f in fetched_frames if not f.empty]
    if not all_frames:
        return pd.DataFrame()

    result = pd.concat(all_frames).sort_index()
    result.index.names = ["symbol", "timestamp"]

    # Filter to the exact requested window in case the cache spans a wider range.
    ts_level = result.index.get_level_values("timestamp")
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    mask = (ts_level >= start_ts) & (ts_level < end_ts)
    result = result.loc[mask]

    # Normalise the timestamp level to microsecond resolution.  pyarrow writes
    # parquet with millisecond timestamps while pandas date_range defaults to
    # seconds; coercing to a common unit avoids dtype mismatches between the
    # cache and non-cache code paths.
    sym_vals = result.index.get_level_values("symbol")
    ts_vals = result.index.get_level_values("timestamp").as_unit("us")
    result.index = pd.MultiIndex.from_arrays([sym_vals, ts_vals], names=["symbol", "timestamp"])
    return result
