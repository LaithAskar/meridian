"""
Per-symbol news headline loader for the Meridian backtester.

Reads parquet files produced by ``backtest.scripts.download_news`` and
returns DataFrames suitable for the sentiment signal wrappers
(``backtest/signals/vader.py``, ``backtest/signals/finbert.py``).

Cache layout
------------
One parquet file per ticker, at ``data/cache/news_{symbol}.parquet``.
Columns (lowercase, normalized):

    date       : pd.Timestamp (tz-naive, day-truncated)
    headline   : str
    publisher  : str
    url        : str

A symbol whose parquet file is absent OR empty returns an empty
DataFrame (the sentiment signal interprets this as "no signal" for
that bar).  Callers must NOT crash on missing news.

Source dataset
--------------
FNSPID — Financial News and Stock Price Integration Dataset
  Dong et al. 2024, arXiv:2402.06698
  https://huggingface.co/datasets/Zihan1004/FNSPID
  License: CC BY-NC 4.0 (non-commercial use only — backtest evidence
  and research artifact are within scope; commercial product
  distribution would require separate licensing.)

Window: news data covers 1999-01-01 → 2023-12-31.  The Meridian
backtest restricts to 2010-01-01 → 2023-12-31 (see DESIGN.md §6).
"""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "cache"

NEWS_COLUMNS: tuple[str, ...] = ("date", "headline", "publisher", "url")

# In-memory cache: (symbol, cache_dir_resolved) -> full processed DataFrame.
# Backtests call load_news once per (symbol, bar_date) — without this cache
# that's ~92 * 3500 = 320k full parquet reads per run.  The cached df holds
# the full date range; per-call window filtering is a cheap mask.
_NEWS_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def clear_news_cache() -> None:
    """Drop the in-memory news cache. Useful between distinct test runs."""
    _NEWS_CACHE.clear()


def _cache_path(symbol: str, cache_dir: Optional[Path] = None) -> Path:
    base = cache_dir if cache_dir is not None else _CACHE_DIR
    return base / f"news_{symbol}.parquet"


def _empty_news() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "headline": pd.Series(dtype="object"),
            "publisher": pd.Series(dtype="object"),
            "url": pd.Series(dtype="object"),
        }
    )


def _load_full(symbol: str, cache_dir: Optional[Path]) -> pd.DataFrame:
    """Read + normalize the full per-symbol parquet, or emit a warning + empty.

    Pure read path — no window filter applied here.  Caller does the window
    filter so the cached df can serve multiple windows.
    """
    path = _cache_path(symbol, cache_dir)

    if not path.exists():
        warnings.warn(
            f"news_data: no cache file for {symbol!r} at {path} — "
            f"returning empty DataFrame.  Run "
            f"`python -m backtest.scripts.download_news` to populate.",
            stacklevel=3,
        )
        return _empty_news()

    df = pd.read_parquet(path)
    if df.empty:
        return _empty_news()

    df.columns = [c.lower() for c in df.columns]
    missing = set(NEWS_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"news_data: cache file {path} is missing required columns: {missing}"
        )

    df = df[list(NEWS_COLUMNS)].copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=False)
    if hasattr(df["date"].dt, "tz") and df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    df = df.dropna(subset=["date"])
    df = df.dropna(subset=["headline"])

    return df.sort_values("date").reset_index(drop=True)


def load_news(
    symbol: str,
    start: date,
    end: date,
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Return news headlines for *symbol* over the inclusive window [start, end].

    If no cache file exists for the symbol, returns an empty DataFrame and
    emits a warning (callers — sentiment signals — must treat empty as
    "no signal for this bar," not as an error).

    Repeated calls for the same symbol hit an in-memory cache of the full
    processed DataFrame; the per-call cost is then just a window-filter mask.

    Returns
    -------
    pd.DataFrame with columns ``date, headline, publisher, url``.
    Sorted by date ascending.  The date column is tz-naive ``datetime64[ns]``.

    Parameters
    ----------
    symbol     : ticker (uppercase, e.g. 'AAPL', 'BRK-B')
    start      : inclusive start date
    end        : inclusive end date
    cache_dir  : override the default ``data/cache/`` directory (used in tests)
    """
    cache_dir_key = str((cache_dir if cache_dir is not None else _CACHE_DIR).resolve())
    key = (symbol, cache_dir_key)

    full = _NEWS_CACHE.get(key)
    if full is None:
        full = _load_full(symbol, cache_dir)
        _NEWS_CACHE[key] = full

    if full.empty:
        return _empty_news()

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    mask = (full["date"] >= start_ts) & (full["date"] <= end_ts)
    return full.loc[mask].reset_index(drop=True)
