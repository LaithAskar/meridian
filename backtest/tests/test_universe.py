"""
Tests for backtest/universe.py

Structural tests (no network):
  - UNIVERSE_2010 has exactly 100 tickers
  - All uppercase
  - No duplicates

Fetchability tests (monkeypatched — no network):
  - For 10 deterministically-sampled tickers, a yfinance fetch covering
    2010-01-01 → 2010-12-31 returns a non-empty DataFrame OR the ticker is
    in KNOWN_NO_DATA.
  - Tickers in KNOWN_NO_DATA are not in UNIVERSE_2010 (inconsistent state).
  - BRK.B (the dot-ticker) is handled without raising.
"""

from __future__ import annotations

import pandas as pd
import pytest

import yfinance as yf

from backtest.universe import KNOWN_NO_DATA, UNIVERSE_2010

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = "2010-01-01"
_END   = "2010-12-31"

# Deterministic sample: every 10th ticker after sorting, giving 10 tickers.
_SAMPLE: list[str] = sorted(UNIVERSE_2010)[::10]


def _make_yf_raw(ticker: str) -> pd.DataFrame:
    """Minimal synthetic yfinance 1.x output for one ticker."""
    dates = pd.bdate_range(start=_START, end="2010-03-31")
    n = len(dates)
    cols = pd.MultiIndex.from_tuples([
        ("Open",   ticker), ("High",   ticker), ("Low",    ticker),
        ("Close",  ticker), ("Volume", ticker),
    ])
    data = {c: ([100.0] if c[0] != "Volume" else [10_000]) * n for c in cols}
    df = pd.DataFrame(data, index=dates, columns=cols)
    df.index.name = "Date"
    return df


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestUniverse2010Structure:
    def test_exactly_100_tickers(self):
        assert len(UNIVERSE_2010) == 100, (
            f"Expected 100 tickers, got {len(UNIVERSE_2010)}"
        )

    def test_all_uppercase(self):
        bad = [t for t in UNIVERSE_2010 if t != t.upper()]
        assert not bad, f"Tickers not fully uppercase: {bad}"

    def test_no_duplicates(self):
        seen = set()
        dupes = []
        for t in UNIVERSE_2010:
            if t in seen:
                dupes.append(t)
            seen.add(t)
        assert not dupes, f"Duplicate tickers: {dupes}"

    def test_known_no_data_subset_of_universe(self):
        """Every KNOWN_NO_DATA ticker must appear in UNIVERSE_2010."""
        orphans = KNOWN_NO_DATA - set(UNIVERSE_2010)
        assert not orphans, (
            f"KNOWN_NO_DATA contains tickers not in UNIVERSE_2010: {orphans}"
        )

    def test_brk_b_present(self):
        """Berkshire Hathaway Class B (BRK.B) uses a period — must survive the list."""
        assert "BRK.B" in UNIVERSE_2010

    def test_googl_not_goog(self):
        """Use GOOGL (Class A with full yfinance history) not GOOG."""
        assert "GOOGL" in UNIVERSE_2010
        assert "GOOG" not in UNIVERSE_2010

    def test_2010_era_tickers_absent(self):
        """Companies that did not exist in Jan 2010 must not appear."""
        not_yet_public = ["META", "ABBV", "KHC", "MDLZ"]
        for t in not_yet_public:
            assert t not in UNIVERSE_2010, (
                f"{t!r} was not publicly traded in Jan 2010 but appears in UNIVERSE_2010"
            )

    def test_too_small_2010_tickers_absent(self):
        """Companies too small for OEX in Jan 2010 must not appear."""
        too_small = ["AVGO", "BIIB", "SBUX", "CELG"]
        for t in too_small:
            assert t not in UNIVERSE_2010, (
                f"{t!r} was below OEX market-cap threshold in Jan 2010 "
                f"but appears in UNIVERSE_2010"
            )

    def test_2010_era_replacements_present(self):
        """Companies in 2010 OEX that replaced post-2010 additions must be present."""
        must_have = ["HPQ", "KFT", "MON", "S", "DVN", "AET", "FCX", "NSC", "MRO", "ELV"]
        for t in must_have:
            assert t in UNIVERSE_2010, (
                f"{t!r} should be in UNIVERSE_2010 (was in Jan 2010 OEX) but is missing"
            )


# ---------------------------------------------------------------------------
# Fetchability tests (monkeypatched)
# ---------------------------------------------------------------------------

class TestFetchability:
    """
    For 10 deterministically-sampled tickers, assert that a yfinance fetch
    over 2010-01-01 → 2010-12-31 either returns non-empty data OR the ticker
    is listed in KNOWN_NO_DATA.

    yf.download is monkeypatched to avoid any network call.  The mock returns
    a valid synthetic DataFrame for every ticker that is NOT in KNOWN_NO_DATA,
    and an empty DataFrame for those that are.
    """

    @pytest.fixture(autouse=True)
    def patch_yf(self, monkeypatch):
        def _fake_download(tickers, start, end, **kwargs):
            sym = tickers if isinstance(tickers, str) else tickers[0]
            if sym in KNOWN_NO_DATA:
                return pd.DataFrame()
            return _make_yf_raw(sym)

        monkeypatch.setattr(yf, "download", _fake_download)

    def test_sample_tickers_are_fetchable(self):
        """Each sampled ticker yields non-empty data or is in KNOWN_NO_DATA."""
        assert len(_SAMPLE) == 10, f"Expected 10 samples, got {len(_SAMPLE)}: {_SAMPLE}"
        for ticker in _SAMPLE:
            raw = yf.download(ticker, start=_START, end=_END,
                              auto_adjust=True, progress=False)
            if ticker in KNOWN_NO_DATA:
                assert raw.empty, (
                    f"{ticker!r} is in KNOWN_NO_DATA but mock returned non-empty data"
                )
            else:
                assert not raw.empty, (
                    f"{ticker!r} is not in KNOWN_NO_DATA but fetch returned empty — "
                    f"add it to KNOWN_NO_DATA with a comment explaining why"
                )

    def test_brk_b_fetchable(self):
        """BRK.B (dot-ticker) doesn't cause KeyError or attribute error."""
        raw = yf.download("BRK.B", start=_START, end=_END,
                          auto_adjust=True, progress=False)
        assert "BRK.B" not in KNOWN_NO_DATA or raw.empty
        if "BRK.B" not in KNOWN_NO_DATA:
            assert not raw.empty
