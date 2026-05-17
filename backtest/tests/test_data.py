"""
Tests for backtest/data.py

All tests monkeypatch yf.download so no network calls are made.  The mock
returns a DataFrame that matches the actual yfinance 1.x shape: MultiIndex
columns (Price, Ticker) with a tz-naive DatetimeIndex.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

import backtest.data as _mod
from backtest.data import _cache_covers, _cache_path, fetch_bars


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_yf_raw(symbol: str, start: date, end: date) -> pd.DataFrame:
    """
    Synthetic yf.download return value matching yfinance 1.x format:
      - MultiIndex columns (Price, Ticker): Open/High/Low/Close/Volume × symbol
      - tz-naive DatetimeIndex covering business days in [start, end]
    """
    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)
    cols = pd.MultiIndex.from_tuples([
        ("Open", symbol), ("High", symbol), ("Low", symbol),
        ("Close", symbol), ("Volume", symbol),
    ])
    data = {
        ("Open", symbol):   [100.0] * n,
        ("High", symbol):   [101.0] * n,
        ("Low", symbol):    [99.0]  * n,
        ("Close", symbol):  [100.5] * n,
        ("Volume", symbol): [10_000] * n,
    }
    df = pd.DataFrame(data, index=dates, columns=cols)
    df.index.name = "Date"
    return df


def _mock_download(syms_data: dict[str, tuple[date, date]]):
    """Return a mock download callable that returns synthetic data keyed by symbol."""
    def _download(symbol, *args, **kwargs):
        s, e = syms_data.get(symbol, (date(2024, 1, 2), date(2024, 1, 5)))
        return _make_yf_raw(symbol, s, e)
    return _download


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Suppress all time.sleep calls so tests run instantly."""
    monkeypatch.setattr("time.sleep", lambda _: None)


# ---------------------------------------------------------------------------
# _cache_covers
# ---------------------------------------------------------------------------

def _write_parquet(path, start: date, end: date) -> None:
    """Write a minimal parquet file whose DatetimeIndex covers [start, end]."""
    dates = pd.bdate_range(start=start, end=end)
    df = pd.DataFrame({"close": 100.0}, index=dates)
    df.index.name = "date"
    df.to_parquet(path)


class TestCacheCovers:
    def test_missing_file_returns_false(self, tmp_path):
        assert not _cache_covers(tmp_path / "ghost.parquet", date(2024, 1, 1), date(2024, 1, 5))

    def test_file_covering_range_returns_true(self, tmp_path):
        path = tmp_path / "AAPL_1d.parquet"
        _write_parquet(path, date(2024, 1, 1), date(2024, 1, 31))
        assert _cache_covers(path, date(2024, 1, 5), date(2024, 1, 20))

    def test_file_not_covering_end_returns_false(self, tmp_path):
        path = tmp_path / "AAPL_1d.parquet"
        _write_parquet(path, date(2024, 1, 1), date(2024, 1, 15))
        assert not _cache_covers(path, date(2024, 1, 1), date(2024, 1, 31))

    def test_file_not_covering_start_returns_false(self, tmp_path):
        path = tmp_path / "AAPL_1d.parquet"
        _write_parquet(path, date(2024, 1, 15), date(2024, 1, 31))
        assert not _cache_covers(path, date(2024, 1, 1), date(2024, 1, 31))

    def test_empty_parquet_returns_false(self, tmp_path):
        path = tmp_path / "empty.parquet"
        df = pd.DataFrame({"close": pd.Series([], dtype="float64")})
        df.index = pd.DatetimeIndex([])
        df.index.name = "date"
        df.to_parquet(path)
        assert not _cache_covers(path, date(2024, 1, 1), date(2024, 1, 5))

    def test_tolerates_short_gap_at_start(self, tmp_path):
        # Cache starts at first trading day after a holiday weekend; request
        # starts on the calendar Saturday before.  Must be considered covered.
        path = tmp_path / "AAPL_1d.parquet"
        _write_parquet(path, date(2010, 1, 4), date(2024, 12, 31))  # Mon → year-end
        assert _cache_covers(path, date(2010, 1, 1), date(2023, 12, 31))

    def test_tolerates_short_gap_at_end(self, tmp_path):
        path = tmp_path / "AAPL_1d.parquet"
        _write_parquet(path, date(2024, 1, 2), date(2024, 1, 26))  # Fri end
        # Request ends 2024-01-31 (Wed); 5-day gap should still satisfy.
        assert _cache_covers(path, date(2024, 1, 2), date(2024, 1, 31))

    def test_does_not_tolerate_large_gap(self, tmp_path):
        # 8 calendar days exceeds the 7-day tolerance.
        path = tmp_path / "AAPL_1d.parquet"
        _write_parquet(path, date(2024, 1, 10), date(2024, 1, 31))
        assert not _cache_covers(path, date(2024, 1, 1), date(2024, 1, 31))


# ---------------------------------------------------------------------------
# fetch_bars — core behaviour
# ---------------------------------------------------------------------------

class TestFetchBars:
    def test_returns_multiindex_dataframe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))
        df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        assert isinstance(df, pd.DataFrame)
        assert isinstance(df.index, pd.MultiIndex)
        assert df.index.names == ["symbol", "date"]
        assert not df.empty

    def test_expected_columns_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))
        df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        for col in ("open", "high", "low", "close", "volume"):
            assert col in df.columns, f"Missing column: {col}"

    def test_multiple_symbols(self, tmp_path, monkeypatch):
        syms = {"AAPL": (date(2024, 1, 2), date(2024, 1, 5)), "MSFT": (date(2024, 1, 2), date(2024, 1, 5))}
        monkeypatch.setattr(_mod.yf, "download", _mock_download(syms))
        df = fetch_bars(["AAPL", "MSFT"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        result_syms = df.index.get_level_values("symbol").unique().tolist()
        assert "AAPL" in result_syms
        assert "MSFT" in result_syms

    def test_empty_symbols_returns_empty_dataframe(self, tmp_path):
        df = fetch_bars([], date(2024, 1, 1), date(2024, 1, 5), cache_dir=tmp_path)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_no_nan_in_ohlcv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))
        df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        for col in ("open", "high", "low", "close", "volume"):
            assert not df[col].isna().any(), f"NaN found in column '{col}'"

    # ---------------------------------------------------------------------------
    # Caching
    # ---------------------------------------------------------------------------

    def test_cache_file_created_after_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))
        fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        assert (tmp_path / "AAPL_1d.parquet").exists()

    def test_cache_hit_skips_download(self, tmp_path, monkeypatch):
        """Second fetch_bars call must not invoke yf.download when cache is warm."""
        mock_dl = MagicMock(side_effect=_mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))
        monkeypatch.setattr(_mod.yf, "download", mock_dl)

        fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)
        assert mock_dl.call_count == 1

        fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)
        assert mock_dl.call_count == 1, "yf.download called on cache hit — caching is broken"

    def test_cached_data_round_trips_correctly(self, tmp_path, monkeypatch):
        """Data written to parquet and read back is numerically identical."""
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))

        df1 = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)
        df2 = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        pd.testing.assert_frame_equal(df1, df2, check_dtype=False)

    # ---------------------------------------------------------------------------
    # Date filtering
    # ---------------------------------------------------------------------------

    def test_date_filter_applied_on_narrow_request(self, tmp_path, monkeypatch):
        """Cache populated with full month; narrow sub-range request returns only those dates."""
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 31))}))

        # Warm the cache with the full month
        fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 31), cache_dir=tmp_path)

        # Narrow request — must come from cache and be filtered
        df = fetch_bars(["AAPL"], date(2024, 1, 10), date(2024, 1, 19), cache_dir=tmp_path)

        dates = df.index.get_level_values("date")
        assert dates.min() >= pd.Timestamp("2024-01-10")
        assert dates.max() <= pd.Timestamp("2024-01-19")

    def test_date_filter_inclusive_on_both_ends(self, tmp_path, monkeypatch):
        """The start and end dates themselves must appear in the result (if trading days)."""
        monkeypatch.setattr(_mod.yf, "download", _mock_download({"AAPL": (date(2024, 1, 2), date(2024, 1, 5))}))
        df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        dates = df.index.get_level_values("date")
        assert pd.Timestamp("2024-01-02") in dates
        assert pd.Timestamp("2024-01-05") in dates
