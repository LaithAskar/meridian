"""
Tests for backtest/run_common.py, backtest/run_vader.py, backtest/run_finbert.py.

All offline — Engine.run() and SPY fetch are monkeypatched.  FinBERT model
is never loaded (stub scorer injected).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest.engine import BacktestResult
import backtest.run_common as rc
import backtest.run_finbert as rfin
import backtest.run_vader as rvd
from backtest.signals.finbert import FinBERTStrategy


# ---------------------------------------------------------------------------
# Synthetic fixtures
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


def _synthetic_result(n_days: int = 100) -> BacktestResult:
    return BacktestResult(
        equity_curve=_make_equity_curve(n_days),
        trades=_make_trades(n_wins=5, n_losses=3),
    )


def _synthetic_spy(start="2020-01-01", n_days: int = 100) -> pd.Series:
    idx = pd.bdate_range(start, periods=n_days)
    return pd.Series(
        [400.0 * (1 + 0.0005 * i) for i in range(n_days)],
        index=idx, name="close",
    )


# ---------------------------------------------------------------------------
# run_common.metrics_for_window
# ---------------------------------------------------------------------------


class TestMetricsForWindow:
    def test_full_metric_shape(self):
        m = rc.metrics_for_window(_make_equity_curve(60), _make_trades(), years=0.25)
        expected = {
            "sharpe", "sharpe_se", "excess_sharpe", "max_drawdown",
            "hit_rate", "avg_win", "avg_loss", "win_loss_ratio",
            "avg_holding_days", "trade_count", "exposure",
            "total_return", "cagr",
        }
        assert set(m.keys()) == expected
        assert m["excess_sharpe"] is None  # no SPY supplied

    def test_empty_curve_returns_error(self):
        m = rc.metrics_for_window(pd.DataFrame(), pd.DataFrame(), years=1.0)
        assert m == {"error": "empty_window"}

    def test_excess_sharpe_present_with_spy(self):
        spy_rets = pd.Series([0.001] * 50, index=pd.bdate_range("2020-01-02", periods=50))
        m = rc.metrics_for_window(_make_equity_curve(50), _make_trades(), years=0.2, spy_returns=spy_rets)
        assert m["excess_sharpe"] is not None
        assert isinstance(m["excess_sharpe"], float)


# ---------------------------------------------------------------------------
# run_common.slice_window
# ---------------------------------------------------------------------------


class TestSliceWindow:
    def test_pre_end_only(self):
        ec = _make_equity_curve(100)  # starts 2020-01-02
        tr = _make_trades()
        # Restrict to first 30 business days
        cutoff = ec.index[30]
        ec_sl, tr_sl = rc.slice_window(ec, tr, end=cutoff.date())
        assert ec_sl.index.max() == cutoff
        assert (pd.to_datetime(tr_sl["exit_ts"]) <= cutoff).all()

    def test_post_start_only(self):
        ec = _make_equity_curve(100)
        tr = _make_trades()
        cutoff = ec.index[50]
        ec_sl, tr_sl = rc.slice_window(ec, tr, start=cutoff.date())
        assert ec_sl.index.min() == cutoff


# ---------------------------------------------------------------------------
# run_common.spy_returns_for_windows
# ---------------------------------------------------------------------------


class TestSpyReturnsForWindows:
    def test_empty_spy_returns_three_empty(self):
        full, pre, post = rc.spy_returns_for_windows(
            pd.Series(dtype=float),
            date(2020, 1, 1), date(2023, 12, 31),
            date(2020, 2, 29), date(2020, 3, 1),
        )
        assert full.empty and pre.empty and post.empty

    def test_three_non_empty_windows(self):
        spy = _synthetic_spy("2020-01-01", n_days=200)
        full, pre, post = rc.spy_returns_for_windows(
            spy, date(2020, 1, 1), date(2020, 7, 1),
            date(2020, 4, 1), date(2020, 4, 2),
        )
        assert not full.empty
        assert not pre.empty
        assert not post.empty


# ---------------------------------------------------------------------------
# run_vader.run_vader_backtest
# ---------------------------------------------------------------------------


class TestRunVADER:
    def test_full_pipeline_writes_outputs(self, monkeypatch, tmp_path):
        # Stub engine + SPY
        monkeypatch.setattr("backtest.run_vader.Engine.run", lambda self: _synthetic_result(100))
        monkeypatch.setattr("backtest.run_vader.load_spy_close", lambda s, e: _synthetic_spy(s.isoformat(), 100))

        metrics = rvd.run_vader_backtest(
            universe=["AAPL", "MSFT"],
            start=date(2020, 1, 1), end=date(2020, 6, 1),
            max_positions=5, initial_cash=100_000.0,
            output_dir=tmp_path / "vader",
        )

        # Output files exist
        assert (tmp_path / "vader" / "equity_curve.csv").exists()
        assert (tmp_path / "vader" / "trades.csv").exists()
        assert (tmp_path / "vader" / "spy_curve.csv").exists()
        assert (tmp_path / "vader" / "metrics.json").exists()

        # Metrics shape
        assert metrics["strategy"] == "vader"
        assert metrics["parameters"]["threshold"] == 0.35
        assert "full_window" in metrics
        assert "pre_covid" in metrics
        assert "post_covid" in metrics
        assert metrics["benchmark"]["name"] == "SPY buy-and-hold"

        # JSON written matches returned dict
        with open(tmp_path / "vader" / "metrics.json") as fh:
            on_disk = json.load(fh)
        assert on_disk["strategy"] == "vader"

    def test_no_spy_data_still_completes(self, monkeypatch, tmp_path):
        monkeypatch.setattr("backtest.run_vader.Engine.run", lambda self: _synthetic_result(50))
        monkeypatch.setattr("backtest.run_vader.load_spy_close", lambda s, e: pd.Series(dtype=float))

        metrics = rvd.run_vader_backtest(
            universe=["AAPL"], start=date(2020, 1, 1), end=date(2020, 3, 1),
            max_positions=5, initial_cash=100_000.0,
            output_dir=tmp_path / "vader",
        )

        # spy_curve.csv NOT written; metrics.benchmark is None
        assert not (tmp_path / "vader" / "spy_curve.csv").exists()
        assert metrics["benchmark"] is None


# ---------------------------------------------------------------------------
# run_finbert.run_finbert_backtest
# ---------------------------------------------------------------------------


class _StubScorer:
    """Inject this into FinBERTStrategy so no real FinBERT model is loaded."""
    def score(self, text: str) -> float:
        # Anything works — we don't drive trades from the engine stub
        return 0.0
    def save_cache(self) -> None:
        pass


class TestRunFinBERT:
    def test_full_pipeline_writes_outputs(self, monkeypatch, tmp_path):
        # Stub engine + SPY
        monkeypatch.setattr("backtest.run_finbert.Engine.run", lambda self: _synthetic_result(80))
        monkeypatch.setattr("backtest.run_finbert.load_spy_close", lambda s, e: _synthetic_spy(s.isoformat(), 80))

        # Make FinBERTStrategy ALWAYS use a stub scorer to avoid model load
        original_init = FinBERTStrategy.__init__
        def stub_init(self, *args, **kwargs):
            kwargs["scorer"] = _StubScorer()
            return original_init(self, *args, **kwargs)
        monkeypatch.setattr(FinBERTStrategy, "__init__", stub_init)

        metrics = rfin.run_finbert_backtest(
            universe=["AAPL"], start=date(2020, 1, 1), end=date(2020, 4, 1),
            max_positions=5, initial_cash=100_000.0,
            output_dir=tmp_path / "finbert",
        )

        for fn in ("equity_curve.csv", "trades.csv", "spy_curve.csv", "metrics.json"):
            assert (tmp_path / "finbert" / fn).exists(), f"Missing output: {fn}"

        assert metrics["strategy"] == "finbert"
        assert metrics["parameters"]["threshold"] == 0.6
        assert metrics["parameters"]["device"] == "cpu"

    def test_save_cache_called_even_on_engine_failure(self, monkeypatch, tmp_path):
        # Engine raises mid-run; cache must still be saved
        def failing_run(self):
            raise RuntimeError("engine blew up")
        monkeypatch.setattr("backtest.run_finbert.Engine.run", failing_run)

        save_calls = {"n": 0}
        class CountingScorer:
            def score(self, t): return 0.0
            def save_cache(self): save_calls["n"] += 1

        original_init = FinBERTStrategy.__init__
        def stub_init(self, *args, **kwargs):
            kwargs["scorer"] = CountingScorer()
            return original_init(self, *args, **kwargs)
        monkeypatch.setattr(FinBERTStrategy, "__init__", stub_init)

        with pytest.raises(RuntimeError, match="engine blew up"):
            rfin.run_finbert_backtest(
                universe=["AAPL"], start=date(2020, 1, 1), end=date(2020, 3, 1),
                output_dir=tmp_path / "finbert",
            )

        assert save_calls["n"] == 1
