"""
Tests for backtest/metrics.py.

All tests use entirely synthetic data — no network or file I/O.

Design note: where we test a formula rather than a hardcoded expected value (e.g.
sharpe), we deliberately recompute the formula inline so the test documents the
spec rather than just asserting a magic number.  This makes it obvious if the
formula changes.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import (
    avg_holding_period,
    avg_win_loss,
    cagr,
    exposure,
    hit_rate,
    max_drawdown,
    sharpe,
    sharpe_se,
    total_return,
)

# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------

def _returns(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _equity_series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2020-01-02", periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def _equity_df(values: list[float], num_positions: list[int] | None = None) -> pd.DataFrame:
    eq = _equity_series(values)
    n = len(values)
    if num_positions is None:
        num_positions = [1 if i > 0 else 0 for i in range(n)]
    return pd.DataFrame(
        {
            "equity": eq,
            "cash": [0.0] * n,
            "num_positions": num_positions,
        },
        index=eq.index,
    )


def _make_trades(pnls: list[float], holding_days: list[int] | None = None) -> pd.DataFrame:
    """Build a minimal trades DataFrame with just the columns metrics.py needs."""
    n = len(pnls)
    if holding_days is None:
        holding_days = [5] * n
    ts_entry = pd.Timestamp("2020-01-02")
    ts_exit  = pd.Timestamp("2020-01-09")
    return pd.DataFrame(
        {
            "symbol":      ["AAPL"] * n,
            "entry_ts":    [ts_entry] * n,
            "exit_ts":     [ts_exit] * n,
            "qty":         [10.0] * n,
            "entry_price": [100.0] * n,
            "exit_price":  [p / 10.0 + 100.0 for p in pnls],
            "pnl":         pnls,
            "holding_days": holding_days,
        }
    )


# ---------------------------------------------------------------------------
# sharpe
# ---------------------------------------------------------------------------

class TestSharpe:
    def test_empty_returns_zero(self):
        assert sharpe(pd.Series([], dtype=float)) == pytest.approx(0.0)

    def test_single_observation_zero(self):
        """A single observation has no variance → std=0 → 0.0."""
        assert sharpe(_returns([0.01])) == pytest.approx(0.0)

    def test_all_zero_returns_zero(self):
        assert sharpe(_returns([0.0] * 252)) == pytest.approx(0.0)

    def test_formula_matches_spec(self):
        """SR = mean / std(ddof=1) * sqrt(252).  Verify against inline formula."""
        vals = [0.01, 0.02, -0.01, 0.005, -0.003, 0.015]
        r = _returns(vals)
        expected = r.mean() / r.std(ddof=1) * math.sqrt(252)
        assert sharpe(r) == pytest.approx(expected, rel=1e-9)

    def test_negative_mean_gives_negative_sharpe(self):
        rng = np.random.default_rng(42)
        r = pd.Series(rng.normal(loc=-0.002, scale=0.01, size=500))
        assert sharpe(r) < 0.0

    def test_positive_mean_gives_positive_sharpe(self):
        rng = np.random.default_rng(0)
        r = pd.Series(rng.normal(loc=0.001, scale=0.01, size=500))
        assert sharpe(r) > 0.0

    def test_unsupported_freq_raises(self):
        with pytest.raises(ValueError, match="only 'daily'"):
            sharpe(_returns([0.001] * 50), freq="hourly")

    def test_annualisation_by_sqrt_252(self):
        """
        SR computed with a 2-element series: just verify the sqrt(252) factor.
        mean([a, b]) = (a+b)/2, std([a,b]) = |a-b|/sqrt(2) ... actually let's
        use a deterministic 10-element series with known mean and std.
        """
        # 10 values designed so mean = 0.01 and std_ddof1 can be computed
        vals = [0.01, 0.02, 0.01, 0.00, 0.01, 0.02, 0.01, 0.00, 0.01, 0.01]
        r = _returns(vals)
        sr = sharpe(r)
        expected = r.mean() / r.std(ddof=1) * math.sqrt(252)
        assert sr == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# sharpe_se
# ---------------------------------------------------------------------------

class TestSharpeSE:
    def test_fewer_than_two_obs_is_nan(self):
        assert math.isnan(sharpe_se(pd.Series([], dtype=float)))
        assert math.isnan(sharpe_se(_returns([0.01])))

    def test_formula_matches_spec(self):
        """SE = sqrt((1 + SR^2 / 2) / n)."""
        rng = np.random.default_rng(7)
        r = pd.Series(rng.normal(loc=0.001, scale=0.01, size=252))
        sr = sharpe(r)
        expected_se = math.sqrt((1.0 + sr ** 2 / 2.0) / len(r))
        assert sharpe_se(r) == pytest.approx(expected_se, rel=1e-9)

    def test_zero_sharpe_se_is_1_over_sqrt_n(self):
        """When SR=0 (all-zero returns), SE = sqrt(1/n) = 1/sqrt(n)."""
        # Use a mixed series where mean≈0 and std>0 so SR≈0
        r = _returns([0.01, -0.01] * 100)  # mean=0, std>0
        sr = sharpe(r)
        assert abs(sr) < 0.01  # confirm SR ≈ 0
        expected_se = math.sqrt((1.0 + sr ** 2 / 2.0) / len(r))
        assert sharpe_se(r) == pytest.approx(expected_se, rel=1e-6)

    def test_se_decreases_with_more_data(self):
        """More observations → smaller SE."""
        rng = np.random.default_rng(99)
        small = pd.Series(rng.normal(loc=0.001, scale=0.01, size=50))
        large = pd.Series(rng.normal(loc=0.001, scale=0.01, size=2000))
        assert sharpe_se(large) < sharpe_se(small)


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_empty_curve_zero(self):
        assert max_drawdown(_equity_series([])) == pytest.approx(0.0)

    def test_single_value_zero(self):
        assert max_drawdown(_equity_series([100.0])) == pytest.approx(0.0)

    def test_monotonic_increase_zero(self):
        assert max_drawdown(_equity_series([100, 110, 120, 130])) == pytest.approx(0.0)

    def test_flat_curve_zero(self):
        assert max_drawdown(_equity_series([100, 100, 100])) == pytest.approx(0.0)

    def test_simple_drawdown(self):
        """Peak=110 at bar 1, trough=90 at bar 2: DD = (90-110)/110 ≈ 0.1818."""
        curve = _equity_series([100.0, 110.0, 90.0])
        dd = max_drawdown(curve)
        expected = (110.0 - 90.0) / 110.0
        assert dd == pytest.approx(expected, rel=1e-9)

    def test_drawdown_from_initial_peak(self):
        """Drawdown from opening high: 100 → 80 = 20%."""
        dd = max_drawdown(_equity_series([100.0, 80.0, 90.0]))
        assert dd == pytest.approx(0.20, rel=1e-9)

    def test_returns_positive_magnitude(self):
        """max_drawdown is always ≥ 0 even when equity declines."""
        dd = max_drawdown(_equity_series([200.0, 100.0, 50.0]))
        assert dd > 0.0

    def test_dataframe_input(self):
        """Accepts DataFrame with 'equity' column."""
        df = _equity_df([100.0, 110.0, 80.0])
        dd = max_drawdown(df)
        expected = (110.0 - 80.0) / 110.0
        assert dd == pytest.approx(expected, rel=1e-9)

    def test_recovery_after_drawdown(self):
        """Drawdown is max over the curve; a later recovery doesn't erase it."""
        curve = _equity_series([100.0, 120.0, 60.0, 150.0])
        dd = max_drawdown(curve)
        # Peak=120, trough=60 → 50% drawdown
        assert dd == pytest.approx(0.50, rel=1e-9)


# ---------------------------------------------------------------------------
# hit_rate
# ---------------------------------------------------------------------------

class TestHitRate:
    def test_empty_trades_zero(self):
        assert hit_rate(pd.DataFrame(columns=["pnl"])) == pytest.approx(0.0)

    def test_all_winners(self):
        assert hit_rate(_make_trades([10.0, 20.0, 5.0])) == pytest.approx(1.0)

    def test_all_losers(self):
        assert hit_rate(_make_trades([-10.0, -5.0])) == pytest.approx(0.0)

    def test_fifty_fifty(self):
        assert hit_rate(_make_trades([10.0, -10.0])) == pytest.approx(0.5)

    def test_exact_fraction(self):
        """3 wins out of 5 → 0.6."""
        assert hit_rate(_make_trades([10.0, -5.0, 8.0, -3.0, 12.0])) == pytest.approx(0.6)

    def test_zero_pnl_not_counted_as_win(self):
        """Breakeven trades (pnl == 0) are NOT counted as wins."""
        assert hit_rate(_make_trades([0.0, 0.0])) == pytest.approx(0.0)

    def test_mix_with_zero(self):
        """1 win, 1 breakeven, 1 loss → 1/3 hit rate."""
        assert hit_rate(_make_trades([10.0, 0.0, -5.0])) == pytest.approx(1.0 / 3.0)


# ---------------------------------------------------------------------------
# avg_win_loss
# ---------------------------------------------------------------------------

class TestAvgWinLoss:
    def test_empty_trades_all_nan(self):
        result = avg_win_loss(pd.DataFrame(columns=["pnl"]))
        assert math.isnan(result["avg_win"])
        assert math.isnan(result["avg_loss"])
        assert math.isnan(result["win_loss_ratio"])

    def test_all_winners_no_avg_loss(self):
        result = avg_win_loss(_make_trades([10.0, 20.0]))
        assert result["avg_win"] == pytest.approx(15.0)
        assert math.isnan(result["avg_loss"])
        assert math.isnan(result["win_loss_ratio"])

    def test_all_losers_no_avg_win(self):
        result = avg_win_loss(_make_trades([-10.0, -20.0]))
        assert math.isnan(result["avg_win"])
        assert result["avg_loss"] == pytest.approx(-15.0)
        assert math.isnan(result["win_loss_ratio"])

    def test_avg_win_positive(self):
        result = avg_win_loss(_make_trades([10.0, 20.0, -5.0]))
        assert result["avg_win"] > 0.0

    def test_avg_loss_negative(self):
        result = avg_win_loss(_make_trades([10.0, -5.0, -15.0]))
        assert result["avg_loss"] < 0.0

    def test_win_loss_ratio_known_value(self):
        """avg_win=15, avg_loss=-10 → ratio=1.5."""
        result = avg_win_loss(_make_trades([10.0, 20.0, -10.0]))
        assert result["avg_win"]       == pytest.approx(15.0)
        assert result["avg_loss"]      == pytest.approx(-10.0)
        assert result["win_loss_ratio"] == pytest.approx(1.5)

    def test_win_loss_ratio_positive(self):
        result = avg_win_loss(_make_trades([5.0, -3.0, 7.0, -2.0]))
        assert result["win_loss_ratio"] > 0.0


# ---------------------------------------------------------------------------
# exposure
# ---------------------------------------------------------------------------

class TestExposure:
    def test_empty_curve_zero(self):
        df = pd.DataFrame(columns=["equity", "cash", "num_positions"])
        assert exposure(df) == pytest.approx(0.0)

    def test_no_positions_zero(self):
        df = _equity_df([100.0] * 5, num_positions=[0, 0, 0, 0, 0])
        assert exposure(df) == pytest.approx(0.0)

    def test_always_in_market_one(self):
        df = _equity_df([100.0] * 4, num_positions=[1, 2, 3, 1])
        assert exposure(df) == pytest.approx(1.0)

    def test_half_exposed(self):
        df = _equity_df([100.0] * 4, num_positions=[0, 1, 0, 1])
        assert exposure(df) == pytest.approx(0.5)

    def test_three_quarter_exposed(self):
        df = _equity_df([100.0] * 4, num_positions=[1, 1, 0, 1])
        assert exposure(df) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# cagr
# ---------------------------------------------------------------------------

class TestCAGR:
    def test_double_in_ten_years(self):
        """$100 → $200 over 10 years ≈ 7.177% CAGR."""
        eq = _equity_series([100.0, 200.0])
        result = cagr(eq, years=10.0)
        assert result == pytest.approx(2.0 ** (1.0 / 10.0) - 1.0, rel=1e-9)

    def test_flat_equity_zero(self):
        eq = _equity_series([100.0, 100.0, 100.0])
        assert cagr(eq, years=1.0) == pytest.approx(0.0, abs=1e-12)

    def test_negative_growth(self):
        """Losing half in 5 years → negative CAGR."""
        eq = _equity_series([200.0, 100.0])
        result = cagr(eq, years=5.0)
        assert result < 0.0
        assert result == pytest.approx(0.5 ** (1.0 / 5.0) - 1.0, rel=1e-9)

    def test_empty_curve_zero(self):
        assert cagr(_equity_series([]), years=1.0) == pytest.approx(0.0)

    def test_zero_years_raises(self):
        with pytest.raises(ValueError):
            cagr(_equity_series([100.0, 110.0]), years=0.0)

    def test_negative_years_raises(self):
        with pytest.raises(ValueError):
            cagr(_equity_series([100.0, 110.0]), years=-5.0)

    def test_zero_initial_raises(self):
        with pytest.raises(ValueError, match="zero"):
            cagr(_equity_series([0.0, 100.0]), years=1.0)

    def test_dataframe_input(self):
        df = _equity_df([100.0, 121.0])
        # 21% in 2 years → CAGR = 1.21^(1/2) - 1 = 0.10
        assert cagr(df, years=2.0) == pytest.approx(1.21 ** 0.5 - 1.0, rel=1e-9)

    def test_14_year_full_window(self):
        """Sanity check for the actual 2010-2024 window (14 years)."""
        eq = _equity_series([1_000_000.0, 4_000_000.0])
        # 4× in 14 years
        assert cagr(eq, years=14.0) == pytest.approx(4.0 ** (1.0 / 14.0) - 1.0, rel=1e-9)


# ---------------------------------------------------------------------------
# total_return
# ---------------------------------------------------------------------------

class TestTotalReturn:
    def test_flat_zero(self):
        assert total_return(_equity_series([100.0, 100.0])) == pytest.approx(0.0)

    def test_double_is_one(self):
        assert total_return(_equity_series([100.0, 200.0])) == pytest.approx(1.0)

    def test_half_is_minus_half(self):
        assert total_return(_equity_series([200.0, 100.0])) == pytest.approx(-0.5)

    def test_dataframe_input(self):
        df = _equity_df([100.0, 150.0])
        assert total_return(df) == pytest.approx(0.5)

    def test_empty_curve_raises(self):
        with pytest.raises(ValueError):
            total_return(_equity_series([]))

    def test_zero_initial_raises(self):
        with pytest.raises(ValueError):
            total_return(_equity_series([0.0, 100.0]))


# ---------------------------------------------------------------------------
# avg_holding_period
# ---------------------------------------------------------------------------

class TestAvgHoldingPeriod:
    def test_empty_trades_nan(self):
        assert math.isnan(avg_holding_period(pd.DataFrame(columns=["holding_days"])))

    def test_uniform_holding_period(self):
        trades = _make_trades([10.0, -5.0, 8.0], holding_days=[5, 5, 5])
        assert avg_holding_period(trades) == pytest.approx(5.0)

    def test_mean_of_mixed_periods(self):
        trades = _make_trades([10.0, -5.0], holding_days=[10, 20])
        assert avg_holding_period(trades) == pytest.approx(15.0)

    def test_single_trade(self):
        trades = _make_trades([100.0], holding_days=[7])
        assert avg_holding_period(trades) == pytest.approx(7.0)
