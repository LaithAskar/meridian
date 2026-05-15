"""
Tests for backtest/data.py

All tests mock _fetch_from_api so they run without Alpaca credentials.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest.data import _cache_covers, _cache_path, fetch_bars


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bars(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    """Build a synthetic (symbol, timestamp) multi-index DataFrame."""
    rows = []
    for sym in symbols:
        for ts in pd.date_range(start=start, end=end, freq="1h", tz="UTC"):
            rows.append(
                {
                    "symbol": sym,
                    "timestamp": ts,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 10_000,
                    "trade_count": 200,
                    "vwap": 100.2,
                }
            )
    df = pd.DataFrame(rows).set_index(["symbol", "timestamp"])
    return df


# ---------------------------------------------------------------------------
# _cache_covers
# ---------------------------------------------------------------------------

class TestCacheCovers:
    def test_missing_file_returns_false(self, tmp_path):
        assert not _cache_covers(tmp_path / "ghost.parquet", date(2024, 1, 1), date(2024, 1, 5))

    def test_file_covering_range_returns_true(self, tmp_path):
        df = _make_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))
        path = tmp_path / "AAPL_1Hour.parquet"
        df.to_parquet(path)
        assert _cache_covers(path, date(2024, 1, 5), date(2024, 1, 20))

    def test_file_not_covering_full_range_returns_false(self, tmp_path):
        # Cache only goes up to Jan 15; request wants up to Jan 31
        df = _make_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 15))
        path = tmp_path / "AAPL_1Hour.parquet"
        df.to_parquet(path)
        assert not _cache_covers(path, date(2024, 1, 1), date(2024, 1, 31))

    def test_empty_parquet_returns_false(self, tmp_path):
        df = pd.DataFrame(columns=["open"]).set_index(
            pd.MultiIndex.from_tuples([], names=["symbol", "timestamp"])
        )
        path = tmp_path / "empty.parquet"
        df.to_parquet(path)
        assert not _cache_covers(path, date(2024, 1, 1), date(2024, 1, 5))


# ---------------------------------------------------------------------------
# fetch_bars — happy path
# ---------------------------------------------------------------------------

class TestFetchBars:
    def test_returns_multiindex_dataframe(self, tmp_path):
        synthetic = _make_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        assert isinstance(df, pd.DataFrame)
        assert isinstance(df.index, pd.MultiIndex)
        assert df.index.names == ["symbol", "timestamp"]
        assert not df.empty

    def test_expected_columns_present(self, tmp_path):
        synthetic = _make_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        for col in ("open", "high", "low", "close", "volume"):
            assert col in df.columns, f"missing column: {col}"

    def test_multiple_symbols(self, tmp_path):
        synthetic = _make_bars(["AAPL", "MSFT"], date(2024, 1, 2), date(2024, 1, 5))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            df = fetch_bars(
                ["AAPL", "MSFT"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path
            )

        symbols_in_result = df.index.get_level_values("symbol").unique().tolist()
        assert "AAPL" in symbols_in_result
        assert "MSFT" in symbols_in_result

    def test_cache_hit_skips_api(self, tmp_path):
        """Second call to fetch_bars must not invoke _fetch_from_api."""
        synthetic = _make_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5))

        with patch("backtest.data._fetch_from_api", return_value=synthetic) as mock_api:
            # First call — populates cache
            fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)
            assert mock_api.call_count == 1

            # Second call — should read from parquet, never call API
            fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)
            assert mock_api.call_count == 1, "API was called on cache hit — caching broken"

    def test_cache_file_created_after_fetch(self, tmp_path):
        synthetic = _make_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        assert (tmp_path / "AAPL_1Hour.parquet").exists()

    def test_cached_data_matches_original(self, tmp_path):
        synthetic = _make_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            df1 = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)
            df2 = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        pd.testing.assert_frame_equal(df1, df2)

    def test_date_filter_applied(self, tmp_path):
        # Cache holds a wide range; request asks for a narrow sub-range.
        synthetic = _make_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            # Populate cache with full month
            fetch_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31), cache_dir=tmp_path)
            # Now request just 3 days — should come from cache, filtered
            df = fetch_bars(["AAPL"], date(2024, 1, 10), date(2024, 1, 12), cache_dir=tmp_path)

        ts_vals = df.index.get_level_values("timestamp")
        assert ts_vals.min() >= pd.Timestamp("2024-01-10", tz="UTC")
        assert ts_vals.max() < pd.Timestamp("2024-01-13", tz="UTC")

    def test_empty_result_for_no_symbols(self, tmp_path):
        df = fetch_bars([], date(2024, 1, 1), date(2024, 1, 5), cache_dir=tmp_path)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_no_nan_in_ohlcv(self, tmp_path):
        synthetic = _make_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5))
        with patch("backtest.data._fetch_from_api", return_value=synthetic):
            df = fetch_bars(["AAPL"], date(2024, 1, 2), date(2024, 1, 5), cache_dir=tmp_path)

        for col in ("open", "high", "low", "close", "volume"):
            assert not df[col].isna().any(), f"NaN found in {col}"
