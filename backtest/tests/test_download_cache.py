"""
Tests for backtest/scripts/download_cache.py.

All tests are fully offline — fetch_bars is monkeypatched so no network I/O
occurs.  We verify the module constants, dry-run path, download-success path,
and the sys.exit(1) path when every symbol fails.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import backtest.scripts.download_cache as dc
from backtest.universe import UNIVERSE_2010


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_download_symbols_contains_full_universe(self):
        assert set(UNIVERSE_2010).issubset(set(dc.DOWNLOAD_SYMBOLS))

    def test_download_symbols_contains_spy(self):
        assert "SPY" in dc.DOWNLOAD_SYMBOLS

    def test_download_symbols_contains_vix(self):
        assert "^VIX" in dc.DOWNLOAD_SYMBOLS

    def test_download_symbols_count(self):
        # 100 universe tickers + SPY + ^VIX
        assert len(dc.DOWNLOAD_SYMBOLS) == 102

    def test_no_duplicates(self):
        assert len(dc.DOWNLOAD_SYMBOLS) == len(set(dc.DOWNLOAD_SYMBOLS))

    def test_start_before_end(self):
        assert dc.START < dc.END

    def test_start_is_2010(self):
        assert dc.START == date(2010, 1, 1)

    def test_end_is_2024(self):
        assert dc.END == date(2024, 12, 31)


# ---------------------------------------------------------------------------
# _cache_dir
# ---------------------------------------------------------------------------

class TestCacheDir:
    def test_returns_path(self):
        assert isinstance(dc._cache_dir(), Path)

    def test_ends_with_data_cache(self):
        p = dc._cache_dir()
        assert p.parts[-1] == "cache"
        assert p.parts[-2] == "data"

    def test_is_absolute(self):
        assert dc._cache_dir().is_absolute()


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_prints_cached_for_existing_file(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(dc, "_cache_dir", lambda: tmp_path)
        # Create a fake parquet file
        (tmp_path / "AAPL_1d.parquet").write_bytes(b"fake")
        dc.dry_run(["AAPL"])
        out = capsys.readouterr().out
        assert "CACHED" in out

    def test_prints_missing_for_absent_file(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(dc, "_cache_dir", lambda: tmp_path)
        dc.dry_run(["AAPL"])
        out = capsys.readouterr().out
        assert "missing" in out

    def test_summary_line_present(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(dc, "_cache_dir", lambda: tmp_path)
        dc.dry_run(["AAPL", "MSFT"])
        out = capsys.readouterr().out
        # Should report total count
        assert "2" in out


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

def _make_bars(sym: str, n: int = 10) -> pd.DataFrame:
    """Synthetic single-symbol MultiIndex DataFrame matching fetch_bars output."""
    dates = pd.bdate_range("2024-01-01", periods=n)
    idx = pd.MultiIndex.from_tuples([(sym, d) for d in dates], names=["symbol", "date"])
    return pd.DataFrame(
        {"open": [100.0] * n, "high": [101.0] * n,
         "low": [99.0] * n, "close": [100.5] * n, "volume": [1e6] * n},
        index=idx,
    )


class TestDownload:
    def test_returns_empty_failed_list_on_success(self, monkeypatch):
        monkeypatch.setattr(dc, "fetch_bars",
                            lambda syms, *a, **kw: _make_bars(syms[0]))
        failed = dc.download(["AAPL", "MSFT"], date(2024, 1, 1), date(2024, 1, 31))
        assert failed == []

    def test_failed_list_contains_symbol_on_empty_bars(self, monkeypatch):
        monkeypatch.setattr(dc, "fetch_bars",
                            lambda *a, **kw: pd.DataFrame())
        failed = dc.download(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))
        assert "AAPL" in failed

    def test_partial_failure_tracked(self, monkeypatch):
        def _fetch(syms, *a, **kw):
            return _make_bars(syms[0]) if syms[0] == "AAPL" else pd.DataFrame()

        monkeypatch.setattr(dc, "fetch_bars", _fetch)
        failed = dc.download(["AAPL", "FAIL"], date(2024, 1, 1), date(2024, 1, 31))
        assert failed == ["FAIL"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_success(self, monkeypatch):
        monkeypatch.setattr(dc, "fetch_bars",
                            lambda syms, *a, **kw: _make_bars(syms[0]))

    def _patch_all_fail(self, monkeypatch):
        monkeypatch.setattr(dc, "fetch_bars",
                            lambda *a, **kw: pd.DataFrame())

    def test_dry_run_flag_calls_dry_run_not_download(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(dc, "_cache_dir", lambda: tmp_path)
        # fetch_bars should NOT be called in dry-run mode
        call_count = {"n": 0}

        def _fake_fetch(*a, **kw):
            call_count["n"] += 1
            return pd.DataFrame()

        monkeypatch.setattr(dc, "fetch_bars", _fake_fetch)
        dc.main(symbols=["AAPL"], is_dry_run=True)
        assert call_count["n"] == 0

    def test_successful_run_prints_done(self, monkeypatch, capsys):
        self._patch_success(monkeypatch)
        dc.main(symbols=["AAPL", "MSFT"])
        out = capsys.readouterr().out
        assert "Done." in out

    def test_successful_run_prints_next_steps(self, monkeypatch, capsys):
        self._patch_success(monkeypatch)
        dc.main(symbols=["AAPL"])
        out = capsys.readouterr().out
        assert "git add data/cache/" in out
        assert "git push origin main" in out

    def test_all_failed_exits_with_code_1(self, monkeypatch):
        self._patch_all_fail(monkeypatch)
        with pytest.raises(SystemExit) as exc:
            dc.main(symbols=["AAPL"])
        assert exc.value.code == 1

    def test_partial_failure_does_not_exit(self, monkeypatch, capsys):
        def _fetch(syms, *a, **kw):
            return _make_bars(syms[0]) if syms[0] == "AAPL" else pd.DataFrame()

        monkeypatch.setattr(dc, "fetch_bars", _fetch)
        # Should NOT raise SystemExit since at least one symbol succeeded
        dc.main(symbols=["AAPL", "FAIL"])
        out = capsys.readouterr().out
        assert "Done." in out

    def test_uses_full_universe_by_default(self, monkeypatch, capsys):
        calls: list[list[str]] = []

        def _fetch(syms, *a, **kw):
            calls.append(list(syms))
            return _make_bars(syms[0])

        monkeypatch.setattr(dc, "fetch_bars", _fetch)
        dc.main()  # no symbols arg → should use DOWNLOAD_SYMBOLS
        total_fetched = len(calls)
        assert total_fetched == len(dc.DOWNLOAD_SYMBOLS)
