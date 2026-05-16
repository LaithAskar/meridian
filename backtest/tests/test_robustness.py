"""
Tests for backtest/robustness.py.

All engine calls are monkeypatched via backtest.robustness._run_engine so
tests are fully offline — no network or disk I/O occurs.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

import backtest.robustness as rb
from backtest.robustness import (
    _split_folds,
    _trade_sharpe,
    monte_carlo_trades,
    parameter_sensitivity,
    walk_forward,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_equity_curve(
    n: int = 60,
    start_val: float = 1_000_000.0,
    daily_return: float = 0.001,
) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-02", periods=n)
    eq = [start_val * (1 + daily_return) ** i for i in range(n)]
    return pd.DataFrame(
        {"equity": eq, "cash": [start_val * 0.5] * n, "num_positions": [3] * n},
        index=idx,
    )


def _make_trades(n_wins: int = 10, n_losses: int = 4) -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2020-02-01")
    for i in range(n_wins):
        rows.append({
            "symbol": f"WIN{i}",
            "entry_ts": base + pd.Timedelta(days=i * 7),
            "exit_ts":  base + pd.Timedelta(days=i * 7 + 5),
            "qty": 10.0, "entry_price": 100.0, "exit_price": 112.0,
            "pnl": 120.0, "holding_days": 5,
        })
    for i in range(n_losses):
        rows.append({
            "symbol": f"LOSS{i}",
            "entry_ts": base + pd.Timedelta(days=100 + i * 7),
            "exit_ts":  base + pd.Timedelta(days=100 + i * 7 + 3),
            "qty": 10.0, "entry_price": 100.0, "exit_price": 93.0,
            "pnl": -70.0, "holding_days": 3,
        })
    if not rows:
        return pd.DataFrame(columns=[
            "symbol", "entry_ts", "exit_ts", "qty",
            "entry_price", "exit_price", "pnl", "holding_days",
        ])
    return pd.DataFrame(rows)


def _empty_trades() -> pd.DataFrame:
    return _make_trades(0, 0)


def _fake_run_engine(
    ec: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    n_days: int = 60,
):
    """Factory that returns a _run_engine replacement yielding synthetic data."""
    _ec = ec if ec is not None else _make_equity_curve(n_days)
    _tr = trades if trades is not None else _make_trades()

    def _impl(*args: Any, **kwargs: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
        return _ec, _tr

    return _impl


# ---------------------------------------------------------------------------
# _split_folds
# ---------------------------------------------------------------------------

class TestSplitFolds:
    def test_two_folds_cover_full_range(self):
        s, e = date(2020, 1, 1), date(2021, 12, 31)
        folds = _split_folds(s, e, 2)
        assert folds[0][0] == s
        assert folds[-1][1] == e

    def test_five_folds_non_overlapping(self):
        s, e = date(2010, 1, 1), date(2024, 12, 31)
        folds = _split_folds(s, e, 5)
        for i in range(len(folds) - 1):
            # end of fold i must be strictly before start of fold i+1
            assert folds[i][1] < folds[i + 1][0]

    def test_one_fold_equals_full_range(self):
        s, e = date(2015, 6, 1), date(2020, 5, 31)
        folds = _split_folds(s, e, 1)
        assert len(folds) == 1
        assert folds[0] == (s, e)

    def test_n_raises_on_zero(self):
        with pytest.raises(ValueError):
            _split_folds(date(2020, 1, 1), date(2020, 12, 31), 0)

    def test_returns_correct_count(self):
        folds = _split_folds(date(2010, 1, 1), date(2024, 12, 31), 7)
        assert len(folds) == 7

    def test_last_fold_ends_on_end(self):
        e = date(2024, 12, 31)
        folds = _split_folds(date(2010, 1, 1), e, 3)
        assert folds[-1][1] == e


# ---------------------------------------------------------------------------
# parameter_sensitivity
# ---------------------------------------------------------------------------

class TestParameterSensitivity:
    def test_returns_dataframe(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=[5, 10],
        )
        assert isinstance(df, pd.DataFrame)

    def test_index_equals_positions_grid(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        grid = [5, 10, 15]
        df = parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=grid,
        )
        assert list(df.index) == grid

    def test_expected_columns_present(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=[10],
        )
        for col in ("sharpe", "sharpe_se", "max_drawdown", "cagr", "total_return", "trade_count"):
            assert col in df.columns

    def test_engine_called_once_per_grid_value(self, monkeypatch):
        call_count = {"n": 0}

        def _counting_engine(*args: Any, **kwargs: Any):
            call_count["n"] += 1
            return _make_equity_curve(), _make_trades()

        monkeypatch.setattr(rb, "_run_engine", _counting_engine)
        parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=[5, 10, 15, 20],
        )
        assert call_count["n"] == 4

    def test_single_grid_value(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=[10],
        )
        assert len(df) == 1

    def test_default_grid_has_four_values(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = parameter_sensitivity(["AAPL"], date(2020, 1, 1), date(2021, 12, 31))
        assert len(df) == 4

    def test_sharpe_values_are_finite_floats(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=[10, 15],
        )
        assert all(isinstance(v, float) for v in df["sharpe"])
        assert all(np.isfinite(v) for v in df["sharpe"])

    def test_trade_count_matches_fake_trades(self, monkeypatch):
        fake_trades = _make_trades(n_wins=7, n_losses=2)
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine(trades=fake_trades))
        df = parameter_sensitivity(
            ["AAPL"], date(2020, 1, 1), date(2021, 12, 31),
            positions_grid=[10],
        )
        assert df.loc[10, "trade_count"] == len(fake_trades)


# ---------------------------------------------------------------------------
# walk_forward
# ---------------------------------------------------------------------------

class TestWalkForward:
    def test_returns_dataframe(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31))
        assert isinstance(df, pd.DataFrame)

    def test_row_count_equals_n_folds(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31), n_folds=4)
        assert len(df) == 4

    def test_index_is_zero_based(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31), n_folds=3)
        assert list(df.index) == [0, 1, 2]

    def test_expected_columns_present(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31))
        for col in ("fold_start", "fold_end", "years", "sharpe", "sharpe_se",
                    "max_drawdown", "cagr", "total_return", "trade_count"):
            assert col in df.columns

    def test_engine_called_once_per_fold(self, monkeypatch):
        call_count = {"n": 0}

        def _counting_engine(*args: Any, **kwargs: Any):
            call_count["n"] += 1
            return _make_equity_curve(), _make_trades()

        monkeypatch.setattr(rb, "_run_engine", _counting_engine)
        walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31), n_folds=5)
        assert call_count["n"] == 5

    def test_fold_dates_are_iso_strings(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31), n_folds=2)
        for col in ("fold_start", "fold_end"):
            for val in df[col]:
                date.fromisoformat(val)  # raises ValueError if not valid ISO

    def test_years_column_is_positive(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        df = walk_forward(["AAPL"], date(2010, 1, 1), date(2024, 12, 31), n_folds=5)
        assert all(df["years"] > 0)

    def test_first_fold_start_equals_start(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        s = date(2010, 1, 1)
        df = walk_forward(["AAPL"], s, date(2024, 12, 31), n_folds=3)
        assert df.loc[0, "fold_start"] == s.isoformat()

    def test_last_fold_end_equals_end(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        e = date(2024, 12, 31)
        df = walk_forward(["AAPL"], date(2010, 1, 1), e, n_folds=3)
        assert df.loc[df.index[-1], "fold_end"] == e.isoformat()

    def test_single_fold_covers_full_window(self, monkeypatch):
        monkeypatch.setattr(rb, "_run_engine", _fake_run_engine())
        s, e = date(2015, 1, 1), date(2020, 12, 31)
        df = walk_forward(["AAPL"], s, e, n_folds=1)
        assert df.loc[0, "fold_start"] == s.isoformat()
        assert df.loc[0, "fold_end"] == e.isoformat()


# ---------------------------------------------------------------------------
# _trade_sharpe
# ---------------------------------------------------------------------------

class TestTradeSharpe:
    def test_all_positive_returns_positive_sharpe(self):
        returns = np.array([0.02, 0.03, 0.015, 0.025])
        assert _trade_sharpe(returns, annualisation=1.0) > 0

    def test_all_negative_returns_negative_sharpe(self):
        returns = np.array([-0.02, -0.01, -0.03])
        assert _trade_sharpe(returns, annualisation=1.0) < 0

    def test_zero_std_returns_zero(self):
        returns = np.array([0.01, 0.01, 0.01])
        assert _trade_sharpe(returns, annualisation=2.0) == 0.0

    def test_fewer_than_two_returns_zero(self):
        assert _trade_sharpe(np.array([0.05]), annualisation=1.0) == 0.0
        assert _trade_sharpe(np.array([]), annualisation=1.0) == 0.0

    def test_annualisation_scales_linearly(self):
        returns = np.array([0.01, -0.005, 0.02, 0.003])
        sr1 = _trade_sharpe(returns, annualisation=1.0)
        sr2 = _trade_sharpe(returns, annualisation=2.0)
        assert abs(sr2 - 2.0 * sr1) < 1e-10


# ---------------------------------------------------------------------------
# monte_carlo_trades
# ---------------------------------------------------------------------------

class TestMonteCarloTrades:
    def test_empty_trades_returns_all_none(self):
        result = monte_carlo_trades(_empty_trades(), years=1.0)
        assert result["actual_sharpe"] is None
        assert result["p_value"] is None

    def test_single_trade_returns_all_none(self):
        tr = _make_trades(n_wins=1, n_losses=0)
        result = monte_carlo_trades(tr, years=1.0)
        assert result["actual_sharpe"] is None

    def test_required_keys_present(self):
        tr = _make_trades(n_wins=8, n_losses=2)
        result = monte_carlo_trades(tr, years=2.0, n_sims=50, seed=0)
        for key in ("actual_sharpe", "sim_p5", "sim_p25", "sim_p50",
                    "sim_p75", "sim_p95", "p_value", "n_trades", "n_sims"):
            assert key in result

    def test_n_trades_matches_input(self):
        tr = _make_trades(n_wins=8, n_losses=3)
        result = monte_carlo_trades(tr, years=2.0, n_sims=50)
        assert result["n_trades"] == len(tr)

    def test_n_sims_matches_input(self):
        tr = _make_trades(n_wins=5, n_losses=2)
        result = monte_carlo_trades(tr, years=1.5, n_sims=200, seed=7)
        assert result["n_sims"] == 200

    def test_deterministic_with_fixed_seed(self):
        tr = _make_trades(n_wins=10, n_losses=4)
        r1 = monte_carlo_trades(tr, years=2.0, n_sims=100, seed=42)
        r2 = monte_carlo_trades(tr, years=2.0, n_sims=100, seed=42)
        assert r1 == r2

    def test_different_seeds_give_different_results(self):
        # Use continuous-valued P&Ls so bootstrap draws genuinely differ across seeds
        rng = np.random.default_rng(17)
        n = 40
        rows = []
        for i in range(n):
            pnl = float(rng.normal(loc=50.0, scale=300.0))
            rows.append({
                "symbol": f"T{i}", "entry_ts": pd.Timestamp("2020-01-01"),
                "exit_ts": pd.Timestamp("2020-06-01"),
                "qty": 10.0, "entry_price": 100.0, "exit_price": 100.0 + pnl / 10,
                "pnl": pnl, "holding_days": 10,
            })
        tr = pd.DataFrame(rows)
        r1 = monte_carlo_trades(tr, years=2.0, n_sims=500, seed=0)
        r2 = monte_carlo_trades(tr, years=2.0, n_sims=500, seed=99)
        # Different seeds should produce different bootstrap distributions
        all_same = all(
            r1[k] == r2[k]
            for k in ("sim_p5", "sim_p25", "sim_p50", "sim_p75", "sim_p95")
        )
        assert not all_same

    def test_all_winning_trades_low_p_value(self):
        # Every trade is a winner: bootstrap should almost never flip to ≤ 0
        tr = _make_trades(n_wins=20, n_losses=0)
        result = monte_carlo_trades(tr, years=2.0, n_sims=500, seed=1)
        assert result["actual_sharpe"] > 0
        assert result["p_value"] < 0.05

    def test_all_losing_trades_high_p_value(self):
        # Every trade is a loser: bootstrap should almost always be ≤ 0
        tr = _make_trades(n_wins=0, n_losses=20)
        result = monte_carlo_trades(tr, years=2.0, n_sims=500, seed=2)
        assert result["actual_sharpe"] < 0
        assert result["p_value"] > 0.95

    def test_p_value_is_between_zero_and_one(self):
        tr = _make_trades(n_wins=8, n_losses=4)
        result = monte_carlo_trades(tr, years=2.0, n_sims=200, seed=3)
        assert 0.0 <= result["p_value"] <= 1.0

    def test_percentile_ordering(self):
        tr = _make_trades(n_wins=10, n_losses=5)
        result = monte_carlo_trades(tr, years=3.0, n_sims=300, seed=4)
        assert result["sim_p5"] <= result["sim_p25"] <= result["sim_p50"]
        assert result["sim_p50"] <= result["sim_p75"] <= result["sim_p95"]

    def test_actual_sharpe_is_rounded(self):
        tr = _make_trades(n_wins=10, n_losses=4)
        result = monte_carlo_trades(tr, years=2.0, n_sims=50, seed=5)
        # Should be rounded to 4 decimal places
        assert result["actual_sharpe"] == round(result["actual_sharpe"], 4)

    def test_actual_sharpe_matches_manual_calculation(self):
        tr = _make_trades(n_wins=10, n_losses=4)
        years = 2.0
        result = monte_carlo_trades(tr, years=years, n_sims=50, seed=6)

        trade_returns = (tr["pnl"] / (tr["entry_price"] * tr["qty"])).to_numpy()
        n = len(trade_returns)
        ann = float(np.sqrt(n / years))
        expected = _trade_sharpe(trade_returns, ann)
        assert abs(result["actual_sharpe"] - round(expected, 4)) < 1e-6

    def test_empty_n_trades_is_zero(self):
        result = monte_carlo_trades(_empty_trades(), years=1.0, n_sims=10)
        assert result["n_trades"] == 0
