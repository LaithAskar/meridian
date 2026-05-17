"""
Tests for backtest/news_data.py and backtest/scripts/download_news.py.

No network: a synthetic FNSPID-shaped CSV is written to tmp_path and the
downloader reads from it directly via --skip-download semantics.
"""

from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from backtest.news_data import NEWS_COLUMNS, load_news
from backtest.scripts import download_news as dn


# ---------------------------------------------------------------------------
# Synthetic FNSPID CSV
# ---------------------------------------------------------------------------

_FNSPID_HEADERS = "Date,Article_title,Stock_symbol,Url,Publisher,Author,Article,Lsa_summary,Luhn_summary,Textrank_summary,Lexrank_summary\n"

_FNSPID_ROWS = [
    # in-window, in-universe (AAPL)
    ('2020-06-05 06:30:54 UTC', "Apple beats Q2 estimates",        "AAPL", "https://x.com/a", "Benzinga", "", "", "", "", "", ""),
    ('2021-01-15 12:00:00 UTC', "Apple unveils new iPhone",        "AAPL", "https://x.com/b", "Reuters",  "", "", "", "", "", ""),
    # in-window, in-universe (MSFT)
    ('2019-09-09 00:00:00 UTC', "Microsoft cloud growth strong",   "MSFT", "https://x.com/c", "Bloomberg","", "", "", "", "", ""),
    # in-window, NOT in universe — should be filtered out
    ('2020-06-05 00:00:00 UTC', "Random small-cap news",           "ZZZZ", "https://x.com/d", "Benzinga", "", "", "", "", "", ""),
    # in-universe, BEFORE window (2009-12-31) — should be filtered out
    ('2009-12-31 23:59:59 UTC', "AAPL pre-window headline",        "AAPL", "https://x.com/e", "Reuters",  "", "", "", "", "", ""),
    # in-universe, AFTER window (2024) — should be filtered out
    ('2024-03-01 00:00:00 UTC', "AAPL post-window headline",       "AAPL", "https://x.com/f", "Reuters",  "", "", "", "", "", ""),
    # in-window, in-universe, but headline is NULL — should be dropped
    ('2020-07-01 00:00:00 UTC', None,                              "AAPL", "https://x.com/g", "Reuters",  "", "", "", "", "", ""),
    # in-window, in-universe (BRK-B with dash form)
    ('2022-11-11 00:00:00 UTC', "Berkshire earnings beat",         "BRK-B","https://x.com/h", "WSJ",      "", "", "", "", "", ""),
    # in-window, in-universe (SPY index ETF news)
    ('2020-03-23 00:00:00 UTC', "SPY tracks S&P 500 to lows",      "SPY",  "https://x.com/i", "Bloomberg","", "", "", "", "", ""),
    # Unparseable date — should be coerced to NaT and dropped
    ('not-a-real-date',         "AAPL bad date row",               "AAPL", "https://x.com/j", "Reuters",  "", "", "", "", "", ""),
]


def _write_fnspid_csv(path: Path) -> None:
    """Write a synthetic FNSPID-shaped CSV to *path*."""
    lines = [_FNSPID_HEADERS]
    for r in _FNSPID_ROWS:
        # CSV-escape: quote each non-None field, write empty for None
        cells = []
        for v in r:
            if v is None:
                cells.append("")
            else:
                # Naive quote — fields here don't contain quotes or commas
                cells.append(f'"{v}"')
        lines.append(",".join(cells) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# load_news (backtest/news_data.py)
# ---------------------------------------------------------------------------

class TestLoadNews:
    def test_missing_cache_returns_empty_with_warning(self, tmp_path):
        with pytest.warns(UserWarning, match="no cache file"):
            df = load_news("AAPL", date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)
        assert df.empty
        assert list(df.columns) == list(NEWS_COLUMNS)

    def test_loads_and_filters_by_date(self, tmp_path):
        # Write a parquet with rows inside + outside the requested window
        path = tmp_path / "news_AAPL.parquet"
        pd.DataFrame({
            "date": pd.to_datetime(["2019-12-31", "2020-06-05", "2020-12-31", "2021-01-01"]),
            "headline": ["before", "in1", "in2", "after"],
            "publisher": ["p"] * 4,
            "url": ["u"] * 4,
        }).to_parquet(path)

        df = load_news("AAPL", date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)
        assert list(df["headline"]) == ["in1", "in2"]

    def test_empty_parquet_returns_empty(self, tmp_path):
        path = tmp_path / "news_FOO.parquet"
        pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "headline": pd.Series(dtype="object"),
                "publisher": pd.Series(dtype="object"),
                "url": pd.Series(dtype="object"),
            }
        ).to_parquet(path)

        df = load_news("FOO", date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)
        assert df.empty
        assert list(df.columns) == list(NEWS_COLUMNS)

    def test_no_nan_headlines_in_result(self, tmp_path):
        path = tmp_path / "news_AAPL.parquet"
        pd.DataFrame({
            "date": pd.to_datetime(["2020-06-05", "2020-06-06"]),
            "headline": ["valid", None],
            "publisher": ["p", "p"],
            "url": ["u", "u"],
        }).to_parquet(path)

        df = load_news("AAPL", date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)
        assert len(df) == 1
        assert df["headline"].notna().all()

    def test_result_sorted_by_date(self, tmp_path):
        path = tmp_path / "news_AAPL.parquet"
        pd.DataFrame({
            "date": pd.to_datetime(["2020-06-10", "2020-06-05", "2020-06-08"]),
            "headline": ["c", "a", "b"],
            "publisher": ["p"] * 3,
            "url": ["u"] * 3,
        }).to_parquet(path)

        df = load_news("AAPL", date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)
        assert list(df["headline"]) == ["a", "b", "c"]

    def test_missing_column_raises(self, tmp_path):
        path = tmp_path / "news_AAPL.parquet"
        pd.DataFrame({
            "date": pd.to_datetime(["2020-06-05"]),
            "headline": ["x"],
            # publisher and url missing
        }).to_parquet(path)

        with pytest.raises(ValueError, match="missing required columns"):
            load_news("AAPL", date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)


# ---------------------------------------------------------------------------
# iter_filtered_chunks (backtest/scripts/download_news.py)
# ---------------------------------------------------------------------------

class TestIterFilteredChunks:
    def test_filters_by_symbol_and_date(self, tmp_path):
        csv_path = tmp_path / "fnspid_synth.csv"
        _write_fnspid_csv(csv_path)

        all_kept = pd.concat(
            list(
                dn.iter_filtered_chunks(
                    csv_path,
                    symbols={"AAPL", "MSFT", "BRK-B", "SPY"},
                    start=date(2010, 1, 1),
                    end=date(2023, 12, 31),
                )
            ),
            ignore_index=True,
        )

        # Expected: 2 AAPL (in-window, non-null headline) + 1 MSFT + 1 BRK-B + 1 SPY = 5
        assert len(all_kept) == 5

        kept_symbols = sorted(all_kept["symbol"].unique())
        assert kept_symbols == ["AAPL", "BRK-B", "MSFT", "SPY"]

        # ZZZZ (out-of-universe) must be absent
        assert "ZZZZ" not in set(all_kept["symbol"])

        # No null headlines
        assert all_kept["headline"].notna().all()

    def test_dates_outside_window_filtered(self, tmp_path):
        csv_path = tmp_path / "fnspid_synth.csv"
        _write_fnspid_csv(csv_path)

        all_kept = pd.concat(
            list(
                dn.iter_filtered_chunks(
                    csv_path,
                    symbols={"AAPL"},
                    start=date(2020, 1, 1),
                    end=date(2020, 12, 31),
                )
            ),
            ignore_index=True,
        )
        # Synthetic fixture has 4 AAPL rows total: 2009-12-31, 2020-06-05,
        # 2024-03-01, and a null-headline + an unparseable-date row.  Only the
        # 2020-06-05 one falls inside [2020-01-01, 2020-12-31] AND has a
        # parseable date AND a non-null headline.
        assert len(all_kept) == 1
        for d in all_kept["date"]:
            assert date(2020, 1, 1) <= pd.Timestamp(d).date() <= date(2020, 12, 31)

    def test_output_schema(self, tmp_path):
        csv_path = tmp_path / "fnspid_synth.csv"
        _write_fnspid_csv(csv_path)

        chunks = list(
            dn.iter_filtered_chunks(
                csv_path,
                symbols={"AAPL"},
                start=date(2010, 1, 1),
                end=date(2023, 12, 31),
            )
        )
        assert chunks, "expected at least one non-empty chunk"
        # Schema = symbol + the 4 output columns
        expected = {"date", "headline", "publisher", "url", "symbol"}
        for chunk in chunks:
            assert set(chunk.columns) == expected


# ---------------------------------------------------------------------------
# write_per_symbol_parquets (backtest/scripts/download_news.py)
# ---------------------------------------------------------------------------

class TestWritePerSymbolParquets:
    def test_writes_one_parquet_per_symbol(self, tmp_path):
        chunk = pd.DataFrame({
            "date":      pd.to_datetime(["2020-06-05", "2021-01-15", "2019-09-09"]),
            "headline":  ["aapl 1", "aapl 2", "msft 1"],
            "publisher": ["p"] * 3,
            "url":       ["u"] * 3,
            "symbol":    ["AAPL", "AAPL", "MSFT"],
        })

        counts = dn.write_per_symbol_parquets(
            [chunk],
            symbols=["AAPL", "MSFT", "FOO"],
            cache_dir=tmp_path,
        )

        assert counts == {"AAPL": 2, "MSFT": 1, "FOO": 0}

        # AAPL parquet has 2 rows, sorted by date
        aapl = pd.read_parquet(tmp_path / "news_AAPL.parquet")
        assert len(aapl) == 2
        assert aapl["date"].is_monotonic_increasing
        assert list(aapl["headline"]) == ["aapl 1", "aapl 2"]

        # FOO got an empty parquet (so load_news doesn't crash for it)
        foo = pd.read_parquet(tmp_path / "news_FOO.parquet")
        assert foo.empty
        assert list(foo.columns) == ["date", "headline", "publisher", "url"]

    def test_force_overwrites_existing(self, tmp_path):
        # Pre-populate AAPL with an old row
        path = tmp_path / "news_AAPL.parquet"
        pd.DataFrame({
            "date":      pd.to_datetime(["1999-01-01"]),
            "headline":  ["old"],
            "publisher": ["p"],
            "url":       ["u"],
        }).to_parquet(path)

        new_chunk = pd.DataFrame({
            "date":      pd.to_datetime(["2020-06-05"]),
            "headline":  ["new"],
            "publisher": ["p"],
            "url":       ["u"],
            "symbol":    ["AAPL"],
        })

        # Without --force, the existing non-empty cache is kept
        counts = dn.write_per_symbol_parquets(
            [new_chunk], symbols=["AAPL"], cache_dir=tmp_path, force=False
        )
        assert counts == {"AAPL": 1}  # unchanged (still the 'old' row)
        assert list(pd.read_parquet(path)["headline"]) == ["old"]

        # With --force, the new chunk replaces the old contents
        counts = dn.write_per_symbol_parquets(
            [new_chunk], symbols=["AAPL"], cache_dir=tmp_path, force=True
        )
        assert counts == {"AAPL": 1}
        assert list(pd.read_parquet(path)["headline"]) == ["new"]


# ---------------------------------------------------------------------------
# End-to-end: iter_filtered_chunks -> write_per_symbol_parquets -> load_news
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_pipeline_with_synthetic_csv(self, tmp_path):
        csv_path = tmp_path / "fnspid_synth.csv"
        _write_fnspid_csv(csv_path)

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        symbols = ["AAPL", "MSFT", "BRK-B", "SPY", "ZZZZ_NOT_IN_FNSPID"]

        counts = dn.write_per_symbol_parquets(
            dn.iter_filtered_chunks(
                csv_path,
                symbols=set(symbols),
                start=date(2010, 1, 1),
                end=date(2023, 12, 31),
            ),
            symbols=symbols,
            cache_dir=cache_dir,
        )

        assert counts["AAPL"] == 2
        assert counts["MSFT"] == 1
        assert counts["BRK-B"] == 1
        assert counts["SPY"] == 1
        assert counts["ZZZZ_NOT_IN_FNSPID"] == 0

        # Now load via the public API
        aapl = load_news("AAPL", date(2020, 1, 1), date(2021, 12, 31), cache_dir=cache_dir)
        assert len(aapl) == 2

        zzzz = load_news(
            "ZZZZ_NOT_IN_FNSPID",
            date(2010, 1, 1), date(2023, 12, 31),
            cache_dir=cache_dir,
        )
        assert zzzz.empty
        # Empty result still has the canonical 4-column schema
        assert list(zzzz.columns) == list(NEWS_COLUMNS)
