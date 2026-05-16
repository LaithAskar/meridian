"""
Tests for backtest/run_quant.py.

All tests are fully offline — Engine.run() and fetch_bars() are monkeypatched
to return synthetic data so no network or disk I/O occurs.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest.engine import BacktestResult
import backtest.run_quant as rq
from backtest.run_quant import (
    FULL_END,
    FULL_START,
    PRE_COVID_END,
    POST_COVID_START,
    _benchmark_block,
    _spy_returns_per_window,
    _spy_slice,
    load_spy_vix,
    metrics_for_window,
    run_quant_backtest,
    slice_window,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_equity_curve(n: int = 50, start_val: float = 1_000_000.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-02", periods=n)
    eq = [start_val * (1 + 0.001 * i) for i in range(n)]
    return pd.DataFrame(
        {"equity": eq, "cash": [eq[0]] * n, "num_positions": [3] * n},
        index=idx,
    )


def _make_trades(n_wins: int = 5, n_losses: int = 3) -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2020-03-01")
    for i in range(n_wins):
        rows.append({
            "symbol": f"WIN{i}", "entry_ts": base + pd.Timedelta(days=i * 5),
            "exit_ts": base + pd.Timedelta(days=i * 5 + 3),
            "qty": 10.0, "entry_price": 100.0, "exit_price": 110.0,
            "pnl": 100.0, "holding_days": 3,
        })
    for i in range(n_losses):
        rows.append({
            "symbol": f"LOSS{i}", "entry_ts": base + pd.Timedelta(days=50 + i * 5),
            "exit_ts": base + pd.Timedelta(days=50 + i * 5 + 2),
            "qty": 10.0, "entry_price": 100.0, "exit_price": 95.0,
            "pnl": -50.0, "holding_days": 2,
        })
    if not rows:
        return pd.DataFrame(columns=[
            "symbol", "entry_ts", "exit_ts", "qty",
            "entry_price", "exit_price", "pnl", "holding_days",
        ])
    return pd.DataFrame(rows)


def _empty_trades() -> pd.DataFrame:
    return _make_trades(0, 0)


def _synthetic_result(n_days: int = 100) -> BacktestResult:
    return BacktestResult(
        equity_curve=_make_equity_curve(n_days),
        trades=_make_trades(n_wins=5, n_losses=3),
    )


# ---------------------------------------------------------------------------
# metrics_for_window
# ---------------------------------------------------------------------------

class TestMetricsForWindow:
    def test_returns_all_required_keys(self):
        m = metrics_for_window(_make_equity_curve(), _make_trades(), years=1.0)
        required = {
            "sharpe", "sharpe_se", "max_drawdown", "hit_rate",
            "avg_win", "avg_loss", "win_loss_ratio", "avg_holding_days",
            "trade_count", "exposure", "total_return", "cagr",
        }
        assert required.issubset(m.keys())

    def test_empty_equity_curve_returns_error_dict(self):
        ec = pd.DataFrame(columns=["equity", "cash", "num_positions"])
        m = metrics_for_window(ec, _empty_trades(), years=1.0)
        assert "error" in m

    def test_hit_rate_numerically_correct(self):
        # 5 wins + 3 losses → 5/8
        m = metrics_for_window(_make_equity_curve(), _make_trades(5, 3), years=1.0)
        assert m["hit_rate"] == pytest.approx(5 / 8, abs=1e-4)

    def test_trade_count_correct(self):
        m = metrics_for_window(_make_equity_curve(), _make_trades(4, 2), years=1.0)
        assert m["trade_count"] == 6

    def test_no_trades_yields_none_not_nan(self):
        """avg_win, avg_loss, win_loss_ratio, avg_holding_days must be None (not NaN) when no trades exist."""
        m = metrics_for_window(_make_equity_curve(), _empty_trades(), years=1.0)
        for key in ("avg_win", "avg_loss", "win_loss_ratio", "avg_holding_days"):
            assert m[key] is None, f"Expected None for {key}, got {m[key]!r}"

    def test_sharpe_positive_for_steady_growth(self):
        m = metrics_for_window(_make_equity_curve(252), _empty_trades(), years=1.0)
        assert m["sharpe"] > 0

    def test_max_drawdown_zero_for_monotone_growth(self):
        m = metrics_for_window(_make_equity_curve(100), _empty_trades(), years=1.0)
        assert m["max_drawdown"] == pytest.approx(0.0, abs=1e-6)

    def test_json_serialisable_no_trades(self):
        """Dict must round-trip through json.dumps without NaN / infinity errors."""
        m = metrics_for_window(_make_equity_curve(), _empty_trades(), years=1.0)
        json.dumps(m)  # raises if any value is NaN / Infinity

    def test_json_serialisable_with_trades(self):
        m = metrics_for_window(_make_equity_curve(), _make_trades(), years=1.0)
        json.dumps(m)

    def test_exposure_between_zero_and_one(self):
        m = metrics_for_window(_make_equity_curve(), _make_trades(), years=1.0)
        assert 0.0 <= m["exposure"] <= 1.0

    def test_cagr_positive_for_growing_curve(self):
        m = metrics_for_window(_make_equity_curve(252), _empty_trades(), years=1.0)
        assert m["cagr"] > 0

    def test_total_return_positive_for_growing_curve(self):
        m = metrics_for_window(_make_equity_curve(50), _empty_trades(), years=0.2)
        assert m["total_return"] > 0


# ---------------------------------------------------------------------------
# slice_window
# ---------------------------------------------------------------------------

class TestSliceWindow:

    def setup_method(self):
        idx = pd.bdate_range("2019-01-02", periods=300)
        self.ec = pd.DataFrame(
            {"equity": [1_000_000 + i * 100 for i in range(300)],
             "cash": [500_000] * 300,
             "num_positions": [2] * 300},
            index=idx,
        )
        # Three trades with exit_ts spread across 2019-2020
        self.tr = pd.DataFrame([
            {"symbol": "A", "entry_ts": pd.Timestamp("2019-01-15"),
             "exit_ts": pd.Timestamp("2019-02-01"), "qty": 10.0,
             "entry_price": 100.0, "exit_price": 105.0, "pnl": 50.0, "holding_days": 17},
            {"symbol": "B", "entry_ts": pd.Timestamp("2019-06-01"),
             "exit_ts": pd.Timestamp("2019-07-01"), "qty": 5.0,
             "entry_price": 200.0, "exit_price": 190.0, "pnl": -50.0, "holding_days": 30},
            {"symbol": "C", "entry_ts": pd.Timestamp("2020-01-10"),
             "exit_ts": pd.Timestamp("2020-02-10"), "qty": 8.0,
             "entry_price": 150.0, "exit_price": 160.0, "pnl": 80.0, "holding_days": 31},
        ])

    def test_no_bounds_returns_everything(self):
        ec, tr = slice_window(self.ec, self.tr)
        assert len(ec) == len(self.ec)
        assert len(tr) == len(self.tr)

    def test_end_bound_clips_equity_curve(self):
        ec, _ = slice_window(self.ec, self.tr, end=date(2019, 6, 30))
        assert ec.index.max() <= pd.Timestamp("2019-06-30")

    def test_start_bound_clips_equity_curve(self):
        ec, _ = slice_window(self.ec, self.tr, start=date(2019, 7, 1))
        assert ec.index.min() >= pd.Timestamp("2019-07-01")

    def test_trades_filtered_by_exit_ts(self):
        # Only trade A (exit 2019-02-01) exits before 2019-05-31
        _, tr = slice_window(self.ec, self.tr, end=date(2019, 5, 31))
        assert set(tr["symbol"]) == {"A"}

    def test_empty_trades_pass_through(self):
        ec, tr = slice_window(self.ec, _empty_trades(), end=date(2019, 6, 30))
        assert tr.empty

    def test_covid_split_covers_all_trades(self):
        """Pre + post COVID slices together must contain all trades (none fall in the gap)."""
        _, pre_tr = slice_window(self.ec, self.tr, end=PRE_COVID_END)
        _, post_tr = slice_window(self.ec, self.tr, start=POST_COVID_START)
        # All three trades exit before 2020-02-29 (none exit between 2020-03-01 and later)
        combined = set(pre_tr["symbol"]) | set(post_tr["symbol"])
        assert combined == set(self.tr["symbol"])

    def test_both_bounds_applied_simultaneously(self):
        ec, tr = slice_window(
            self.ec, self.tr,
            start=date(2019, 5, 1), end=date(2019, 8, 31),
        )
        assert ec.index.min() >= pd.Timestamp("2019-05-01")
        assert ec.index.max() <= pd.Timestamp("2019-08-31")
        # Only trade B (exit 2019-07-01) falls in this window
        assert set(tr["symbol"]) == {"B"}


# ---------------------------------------------------------------------------
# load_spy_vix
# ---------------------------------------------------------------------------

class TestLoadSpyVix:

    def _make_spy_vix_bars(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        dates = pd.bdate_range("2020-01-02", periods=5)
        spy = pd.DataFrame(
            {"open": [300.0]*5, "high": [305.0]*5, "low": [295.0]*5,
             "close": [301.0, 302.0, 303.0, 304.0, 305.0],
             "volume": [1e7]*5},
            index=pd.MultiIndex.from_tuples(
                [("SPY", d) for d in dates], names=["symbol", "date"]
            ),
        )
        vix = pd.DataFrame(
            {"open": [15.0]*5, "high": [16.0]*5, "low": [14.0]*5,
             "close": [15.0, 14.5, 15.5, 16.0, 14.0],
             "volume": [0.0]*5},
            index=pd.MultiIndex.from_tuples(
                [("^VIX", d) for d in dates], names=["symbol", "date"]
            ),
        )
        return spy, vix

    def test_returns_close_series_correctly(self, monkeypatch):
        spy_bars, vix_bars = self._make_spy_vix_bars()

        def fake_fetch(symbols, start, end, **kw):
            return spy_bars if symbols == ["SPY"] else vix_bars

        monkeypatch.setattr(rq, "fetch_bars", fake_fetch)
        spy_close, vix_close = load_spy_vix(date(2020, 1, 1), date(2020, 1, 10))

        assert len(spy_close) == 5
        assert len(vix_close) == 5
        assert float(spy_close.iloc[-1]) == pytest.approx(305.0)
        assert float(vix_close.iloc[-1]) == pytest.approx(14.0)

    def test_empty_on_fetch_failure(self, monkeypatch):
        monkeypatch.setattr(rq, "fetch_bars", lambda *a, **kw: pd.DataFrame())
        spy_close, vix_close = load_spy_vix(date(2020, 1, 1), date(2020, 1, 10))
        assert spy_close.empty
        assert vix_close.empty

    def test_returns_datetimeindex(self, monkeypatch):
        spy_bars, vix_bars = self._make_spy_vix_bars()

        def fake_fetch(symbols, *a, **kw):
            return spy_bars if symbols == ["SPY"] else vix_bars

        monkeypatch.setattr(rq, "fetch_bars", fake_fetch)
        spy_close, vix_close = load_spy_vix(date(2020, 1, 1), date(2020, 1, 10))
        assert isinstance(spy_close.index, pd.DatetimeIndex)
        assert isinstance(vix_close.index, pd.DatetimeIndex)


# ---------------------------------------------------------------------------
# run_quant_backtest — integration (fully mocked)
# ---------------------------------------------------------------------------

class TestRunQuantBacktest:
    """
    Integration tests that monkeypatch both load_spy_vix and Engine.run so
    no actual data fetch or engine computation occurs.
    """

    def _patch(self, monkeypatch, n_days: int = 100):
        synthetic = _synthetic_result(n_days)
        monkeypatch.setattr(rq, "load_spy_vix",
                            lambda s, e: (pd.Series(dtype=float), pd.Series(dtype=float)))
        monkeypatch.setattr(rq.Engine, "run", lambda self: synthetic)

    def test_output_files_created(self, monkeypatch, tmp_path):
        self._patch(monkeypatch)
        run_quant_backtest(
            universe=["AAPL", "MSFT"],
            start=date(2020, 1, 1), end=date(2020, 12, 31),
            output_dir=tmp_path,
        )
        assert (tmp_path / "equity_curve.csv").exists()
        assert (tmp_path / "trades.csv").exists()
        assert (tmp_path / "metrics.json").exists()

    def test_metrics_json_top_level_structure(self, monkeypatch, tmp_path):
        self._patch(monkeypatch)
        metrics = run_quant_backtest(
            universe=["AAPL"],
            start=date(2020, 1, 1), end=date(2020, 12, 31),
            output_dir=tmp_path,
        )
        for key in ("run_date", "parameters", "full_window", "pre_covid", "post_covid"):
            assert key in metrics, f"Missing key: {key}"

    def test_metrics_json_parses_correctly(self, monkeypatch, tmp_path):
        """The written file must be valid JSON with no NaN values."""
        self._patch(monkeypatch, n_days=50)
        run_quant_backtest(
            universe=["AAPL"],
            start=date(2020, 1, 1), end=date(2020, 12, 31),
            output_dir=tmp_path,
        )
        with open(tmp_path / "metrics.json") as fh:
            data = json.load(fh)
        assert "full_window" in data

        # Verify no NaN survived into the JSON (json.load would produce strings, not floats)
        def _check_no_nan(obj):
            if isinstance(obj, float):
                assert not math.isnan(obj), f"NaN found in metrics.json: {obj}"
            elif isinstance(obj, dict):
                for v in obj.values():
                    _check_no_nan(v)
            elif isinstance(obj, list):
                for v in obj:
                    _check_no_nan(v)
        _check_no_nan(data)

    def test_parameters_stored_correctly(self, monkeypatch, tmp_path):
        self._patch(monkeypatch)
        metrics = run_quant_backtest(
            universe=["AAPL", "MSFT", "GOOG"],
            start=date(2020, 1, 1), end=date(2020, 12, 31),
            max_positions=7,
            initial_cash=500_000.0,
            output_dir=tmp_path,
        )
        p = metrics["parameters"]
        assert p["universe_size"] == 3
        assert p["max_positions"] == 7
        assert p["initial_cash"] == 500_000.0
        assert p["slippage_bps"] == 5

    def test_spy_curve_written_when_spy_available(self, monkeypatch, tmp_path):
        synthetic = _synthetic_result(50)
        spy_idx = pd.bdate_range("2020-01-02", periods=50)
        spy_series = pd.Series([300.0 + i * 0.5 for i in range(50)], index=spy_idx)

        monkeypatch.setattr(rq, "load_spy_vix",
                            lambda s, e: (spy_series, pd.Series(dtype=float)))
        monkeypatch.setattr(rq.Engine, "run", lambda self: synthetic)

        run_quant_backtest(
            universe=["AAPL"],
            start=date(2020, 1, 1), end=date(2020, 3, 31),
            output_dir=tmp_path,
        )
        assert (tmp_path / "spy_curve.csv").exists()

    def test_spy_curve_not_written_when_spy_empty(self, monkeypatch, tmp_path):
        self._patch(monkeypatch)
        run_quant_backtest(
            universe=["AAPL"],
            start=date(2020, 1, 1), end=date(2020, 3, 31),
            output_dir=tmp_path,
        )
        assert not (tmp_path / "spy_curve.csv").exists()

    def test_equity_curve_csv_is_readable(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, n_days=50)
        run_quant_backtest(
            universe=["AAPL"],
            start=date(2020, 1, 1), end=date(2020, 12, 31),
            output_dir=tmp_path,
        )
        df = pd.read_csv(tmp_path / "equity_curve.csv", index_col=0)
        assert "equity" in df.columns
        assert len(df) == 50

    def test_output_dir_created_if_not_exists(self, monkeypatch, tmp_path):
        self._patch(monkeypatch)
        nested = tmp_path / "deep" / "nested" / "dir"
        assert not nested.exists()
        run_quant_backtest(
            universe=["AAPL"],
            start=date(2020, 1, 1), end=date(2020, 3, 31),
            output_dir=nested,
        )
        assert nested.exists()


# ---------------------------------------------------------------------------
# _nan_to_none
# ---------------------------------------------------------------------------

class TestNanToNone:
    def test_nan_becomes_none(self):
        from backtest.run_quant import _nan_to_none
        assert _nan_to_none(float("nan")) is None

    def test_float_preserved(self):
        from backtest.run_quant import _nan_to_none
        assert _nan_to_none(3.14) == pytest.approx(3.14)

    def test_none_preserved(self):
        from backtest.run_quant import _nan_to_none
        assert _nan_to_none(None) is None

    def test_int_preserved(self):
        from backtest.run_quant import _nan_to_none
        assert _nan_to_none(42) == 42


# ---------------------------------------------------------------------------
# _spy_slice
# ---------------------------------------------------------------------------

class TestSpySlice:
    def _spy(self, n: int = 50) -> pd.Series:
        idx = pd.bdate_range("2019-01-02", periods=n)
        return pd.Series([300.0 + i for i in range(n)], index=idx)

    def test_empty_returns_empty(self):
        assert _spy_slice(pd.Series(dtype=float), date(2019, 1, 1), date(2019, 12, 31)).empty

    def test_clips_to_start_end(self):
        spy = self._spy(100)
        sliced = _spy_slice(spy, date(2019, 2, 1), date(2019, 3, 31))
        assert sliced.index.min() >= pd.Timestamp("2019-02-01")
        assert sliced.index.max() <= pd.Timestamp("2019-03-31")

    def test_full_range_returns_all(self):
        spy = self._spy(50)
        sliced = _spy_slice(spy, date(2018, 1, 1), date(2025, 12, 31))
        assert len(sliced) == len(spy)

    def test_non_overlapping_range_returns_empty(self):
        spy = self._spy(50)  # starts 2019-01-02
        sliced = _spy_slice(spy, date(2015, 1, 1), date(2016, 12, 31))
        assert sliced.empty


# ---------------------------------------------------------------------------
# _spy_returns_per_window
# ---------------------------------------------------------------------------

class TestSpyReturnsPerWindow:
    def _spy(self, n: int = 100) -> pd.Series:
        idx = pd.bdate_range("2010-01-04", periods=n)
        return pd.Series([100.0 * (1.001 ** i) for i in range(n)], index=idx)

    def test_empty_spy_returns_three_empty_series(self):
        empty = pd.Series(dtype=float)
        full, pre, post = _spy_returns_per_window(
            empty, FULL_START, FULL_END, PRE_COVID_END, POST_COVID_START
        )
        assert full.empty and pre.empty and post.empty

    def test_returns_are_pct_change(self):
        spy = self._spy(50)
        full, _, _ = _spy_returns_per_window(
            spy, date(2010, 1, 1), date(2030, 12, 31),
            PRE_COVID_END, POST_COVID_START,
        )
        # pct_change of geometric series should be a constant ≈ 0.001
        assert float(full.mean()) == pytest.approx(0.001, rel=1e-3)

    def test_three_windows_non_overlapping(self):
        spy = self._spy(300)
        full, pre, post = _spy_returns_per_window(
            spy,
            date(2010, 1, 1), date(2030, 12, 31),
            PRE_COVID_END, POST_COVID_START,
        )
        # pre + post should not overlap; full covers both
        assert len(full) >= len(pre) + len(post)


# ---------------------------------------------------------------------------
# _benchmark_block
# ---------------------------------------------------------------------------

class TestBenchmarkBlock:
    def _spy(self, n: int = 252) -> pd.Series:
        idx = pd.bdate_range("2010-01-04", periods=n)
        return pd.Series([100.0 * (1.001 ** i) for i in range(n)], index=idx)

    def test_returns_none_when_spy_empty(self):
        result = _benchmark_block(
            pd.Series(dtype=float),
            FULL_START, FULL_END, 14.0, 10.0, 4.0,
        )
        assert result is None

    def test_returns_dict_with_expected_keys(self):
        spy = self._spy(500)
        result = _benchmark_block(spy, FULL_START, FULL_END, 14.0, 10.0, 4.0)
        assert result is not None
        assert "name" in result
        assert "full_window" in result
        assert "pre_covid" in result
        assert "post_covid" in result

    def test_name_is_spy_buy_and_hold(self):
        spy = self._spy(500)
        result = _benchmark_block(spy, FULL_START, FULL_END, 14.0, 10.0, 4.0)
        assert result["name"] == "SPY buy-and-hold"

    def test_window_has_benchmark_metric_keys(self):
        spy = self._spy(500)
        result = _benchmark_block(spy, FULL_START, FULL_END, 14.0, 10.0, 4.0)
        for window in ("full_window", "pre_covid", "post_covid"):
            assert set(result[window]) == {"sharpe", "max_drawdown", "total_return", "cagr"}

    def test_monotone_spy_gives_positive_sharpe(self):
        spy = self._spy(500)
        result = _benchmark_block(spy, FULL_START, FULL_END, 14.0, 10.0, 4.0)
        # Full window spy is monotone → positive Sharpe
        assert result["full_window"]["sharpe"] is not None
        assert result["full_window"]["sharpe"] > 0.0


# ---------------------------------------------------------------------------
# metrics_for_window — excess_sharpe
# ---------------------------------------------------------------------------

class TestMetricsForWindowExcessSharpe:
    def _spy_returns(self, n: int = 50, daily_mean: float = 0.001) -> pd.Series:
        import numpy as np
        rng = np.random.default_rng(42)
        return pd.Series(rng.normal(loc=daily_mean, scale=0.01, size=n))

    def test_excess_sharpe_none_when_no_spy_returns(self):
        m = metrics_for_window(_make_equity_curve(), _make_trades(), years=1.0)
        assert m["excess_sharpe"] is None

    def test_excess_sharpe_none_when_spy_returns_empty(self):
        m = metrics_for_window(
            _make_equity_curve(), _make_trades(), years=1.0,
            spy_returns=pd.Series(dtype=float),
        )
        assert m["excess_sharpe"] is None

    def test_excess_sharpe_present_when_spy_returns_provided(self):
        m = metrics_for_window(
            _make_equity_curve(252), _empty_trades(), years=1.0,
            spy_returns=self._spy_returns(252),
        )
        assert m["excess_sharpe"] is not None
        assert isinstance(m["excess_sharpe"], float)

    def test_excess_sharpe_equals_strategy_minus_spy_sharpe(self):
        from backtest.metrics import sharpe
        ec = _make_equity_curve(252)
        spy_rets = self._spy_returns(252, daily_mean=0.0005)
        m = metrics_for_window(ec, _empty_trades(), years=1.0, spy_returns=spy_rets)
        strat_rets = ec["equity"].pct_change().dropna()
        expected = round(sharpe(strat_rets) - sharpe(spy_rets), 4)
        assert m["excess_sharpe"] == pytest.approx(expected, abs=1e-4)

    def test_excess_sharpe_in_json_safe_result(self):
        m = metrics_for_window(
            _make_equity_curve(100), _make_trades(), years=1.0,
            spy_returns=self._spy_returns(100),
        )
        json.dumps(m)  # must not raise (no NaN)

    def test_metrics_for_window_has_excess_sharpe_key_always(self):
        """excess_sharpe key must always be present (even when None)."""
        m = metrics_for_window(_make_equity_curve(), _empty_trades(), years=1.0)
        assert "excess_sharpe" in m


# ---------------------------------------------------------------------------
# run_quant_backtest — benchmark in metrics.json
# ---------------------------------------------------------------------------

class TestRunQuantBacktestBenchmark:
    def _spy_series(self, n: int = 100) -> pd.Series:
        idx = pd.bdate_range("2010-01-04", periods=n)
        return pd.Series([300.0 + i * 0.5 for i in range(n)], index=idx)

    def _patch(self, monkeypatch, n_days: int = 100, with_spy: bool = True):
        synthetic = _synthetic_result(n_days)
        spy = self._spy_series(n_days) if with_spy else pd.Series(dtype=float)
        monkeypatch.setattr(rq, "load_spy_vix", lambda s, e: (spy, pd.Series(dtype=float)))
        monkeypatch.setattr(rq.Engine, "run", lambda self: synthetic)

    def test_benchmark_key_present_when_spy_available(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, with_spy=True)
        metrics = run_quant_backtest(
            universe=["AAPL"], start=date(2010, 1, 1), end=date(2024, 12, 31),
            output_dir=tmp_path,
        )
        assert "benchmark" in metrics
        assert metrics["benchmark"] is not None

    def test_benchmark_key_none_when_spy_unavailable(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, with_spy=False)
        metrics = run_quant_backtest(
            universe=["AAPL"], start=date(2010, 1, 1), end=date(2024, 12, 31),
            output_dir=tmp_path,
        )
        assert metrics["benchmark"] is None

    def test_benchmark_windows_present(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, with_spy=True)
        metrics = run_quant_backtest(
            universe=["AAPL"], start=date(2010, 1, 1), end=date(2024, 12, 31),
            output_dir=tmp_path,
        )
        bm = metrics["benchmark"]
        for key in ("full_window", "pre_covid", "post_covid"):
            assert key in bm, f"Missing benchmark window: {key}"

    def test_benchmark_json_serialisable(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, with_spy=True)
        metrics = run_quant_backtest(
            universe=["AAPL"], start=date(2010, 1, 1), end=date(2024, 12, 31),
            output_dir=tmp_path,
        )
        json.dumps(metrics)  # must not raise

    def test_full_window_has_excess_sharpe(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, with_spy=True)
        metrics = run_quant_backtest(
            universe=["AAPL"], start=date(2010, 1, 1), end=date(2024, 12, 31),
            output_dir=tmp_path,
        )
        assert "excess_sharpe" in metrics["full_window"]

    def test_metrics_json_contains_benchmark(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, with_spy=True)
        run_quant_backtest(
            universe=["AAPL"], start=date(2010, 1, 1), end=date(2024, 12, 31),
            output_dir=tmp_path,
        )
        with open(tmp_path / "metrics.json") as fh:
            data = json.load(fh)
        assert "benchmark" in data
