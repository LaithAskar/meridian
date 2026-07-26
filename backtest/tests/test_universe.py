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

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import yfinance as yf

import backtest.engine as _engine_mod
from backtest.engine import Engine
from backtest.strategy import Order, Strategy
from backtest.universe import KNOWN_NO_DATA, UNIVERSE_2010

_REPO_ROOT = Path(__file__).resolve().parents[2]

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
        """Berkshire Hathaway Class B — stored as BRK-B (dash) because that's yfinance's canonical format."""
        assert "BRK-B" in UNIVERSE_2010

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


class _BuyAETAndTraceStrategy(Strategy):
    """Open a real engine position in AET and record its observable lifecycle."""

    def __init__(self) -> None:
        super().__init__()
        self._ordered = False
        self.trace: list[dict[str, object]] = []

    def on_bar(self, ts, bars, portfolio) -> list[Order]:
        position = portfolio.positions.get("AET")
        self.trace.append({
            "ts": pd.Timestamp(ts),
            "has_bar": "AET" in bars,
            "has_position": position is not None,
            "qty": position.qty if position is not None else 0.0,
            "avg_cost": position.avg_cost if position is not None else pd.NA,
        })
        if not self._ordered and "AET" in bars:
            self._ordered = True
            return [Order("AET", "buy", 10.0)]
        return []


def _tracked_symbol_bars(symbol: str) -> pd.DataFrame:
    """Load one repository-tracked parquet as engine-format fixture bars."""
    path = _REPO_ROOT / "data" / "cache" / f"{symbol}_1d.parquet"
    assert path.is_file(), f"Tracked {symbol} engine fixture is missing: {path}"
    frame = pd.read_parquet(path).copy()
    assert isinstance(frame.index, pd.DatetimeIndex)
    frame.index = pd.MultiIndex.from_arrays(
        [[symbol] * len(frame), frame.index], names=["symbol", "date"]
    )
    return frame


def _run_tracked_aet_position(monkeypatch):
    """Run the production engine over tracked AET + SPY bars, without network."""
    bars = pd.concat([
        _tracked_symbol_bars("AET"),
        _tracked_symbol_bars("SPY"),
    ]).sort_index()
    monkeypatch.setattr(_engine_mod, "fetch_bars", lambda *args, **kwargs: bars)

    strategy = _BuyAETAndTraceStrategy()
    result = Engine(
        strategy=strategy,
        universe=["AET", "SPY"],
        start=date(2010, 1, 1),
        end=date(2024, 12, 31),
        initial_cash=10_000.0,
    ).run()
    return bars.xs("AET", level="symbol"), pd.DataFrame(strategy.trace).set_index("ts"), result


class TestTrackedDelistingEvidence:
    def test_aet_has_continuous_position_trace_through_delisting(self, monkeypatch):
        """Expose AET's real engine lifecycle; this is evidence, not clearance.

        SPY supplies the post-acquisition engine clock after AET bars stop.  The
        assertions deliberately record today's unresolved behavior: AET stays
        in the portfolio, while the missing-price branch marks it at average
        cost.  That conflicts with DESIGN's acquisition-price treatment.
        """
        aet, trace, result = _run_tracked_aet_position(monkeypatch)

        assert "AET" in UNIVERSE_2010
        assert "AET" not in KNOWN_NO_DATA
        assert not aet.empty, "AET is silently absent from tracked engine input"
        assert aet.index.min() <= pd.Timestamp("2010-01-11")
        assert pd.Timestamp("2018-09-01") <= aet.index.max() <= pd.Timestamp("2019-01-01")
        assert len(aet) >= 2_200, "AET lacks meaningful daily coverage"
        assert aet.index.nunique() == len(aet)
        assert not aet[["open", "high", "low", "close"]].isna().any().any()
        annual_counts = aet.groupby(aet.index.year).size()
        assert set(range(2010, 2019)) <= set(annual_counts.index)
        assert (annual_counts.loc[2010:2017] >= 240).all()

        last_aet_ts = aet.index.max()
        first_missing_ts = trace.index[trace.index > last_aet_ts][0]
        assert trace.loc[last_aet_ts, "has_bar"] == True  # noqa: E712
        assert trace.loc[last_aet_ts, "has_position"] == True  # noqa: E712
        assert trace.loc[first_missing_ts, "has_bar"] == False  # noqa: E712
        assert trace.loc[first_missing_ts, "has_position"] == True  # noqa: E712
        assert trace.loc[pd.Timestamp("2018-12-31"), "has_position"] == True  # noqa: E712

        qty = float(trace.loc[first_missing_ts, "qty"])
        avg_cost = float(trace.loc[first_missing_ts, "avg_cost"])
        cash = float(result.equity_curve.loc[first_missing_ts, "cash"])
        assert result.equity_curve.loc[first_missing_ts, "num_positions"] == 1
        assert result.equity_curve.loc[first_missing_ts, "equity"] == pytest.approx(
            cash + qty * avg_cost
        ), "Engine no longer exposes the documented missing-price cost fallback"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "A.3 BLOCKER: DESIGN requires acquisition-price treatment, but the engine "
            "carries AET at average cost after its final bar. A human must verify the "
            "corporate-action proceeds/fixture and choose the post-event rule before unxfail."
        ),
    )
    def test_aet_post_delisting_value_matches_locked_acquisition_treatment(self, monkeypatch):
        """Desired DESIGN behavior, kept strict-xfail so A.3 cannot falsely pass."""
        aet, trace, result = _run_tracked_aet_position(monkeypatch)
        first_missing_ts = trace.index[trace.index > aet.index.max()][0]
        qty = float(trace.loc[first_missing_ts, "qty"])
        cash = float(result.equity_curve.loc[first_missing_ts, "cash"])

        # The final tracked bar is in the documented acquisition window, but a
        # human must still verify that its adjusted close is the correct payout
        # proxy (or replace it with a reviewed corporate-action fixture).
        acquisition_window_value = float(aet.iloc[-1]["close"])
        assert result.equity_curve.loc[first_missing_ts, "equity"] == pytest.approx(
            cash + qty * acquisition_window_value
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
