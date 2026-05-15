"""Tests for backtest/notebooks/nb_utils.py."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from backtest.notebooks.nb_utils import (
    METRIC_KEYS,
    WINDOW_LABELS,
    build_metrics_comparison,
    compute_drawdown_series,
    format_metric_val,
    load_spy_results,
    load_strategy_results,
    normalise_equity,
    regime_sharpe_df,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

def _make_equity_df(n: int = 10, initial: float = 100_000.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    eq = [initial * (1.0 + 0.001 * i) for i in range(n)]
    return pd.DataFrame(
        {"equity": eq, "cash": 0.0, "num_positions": 1},
        index=idx,
    )


def _make_trades_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol":      ["AAPL", "MSFT"],
            "entry_ts":    pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "exit_ts":     pd.to_datetime(["2024-01-10", "2024-01-15"]),
            "qty":         [10, 20],
            "entry_price": [100.0, 200.0],
            "exit_price":  [110.0, 190.0],
            "pnl":         [100.0, -200.0],
            "holding_days": [8, 12],
        }
    )


def _make_metrics_dict() -> dict:
    window = {
        "sharpe": 0.85, "sharpe_se": 0.15, "max_drawdown": 0.12,
        "hit_rate": 0.55, "avg_win": 350.0, "avg_loss": -200.0,
        "win_loss_ratio": 1.75, "avg_holding_days": 8.5,
        "trade_count": 42, "exposure": 0.6,
        "total_return": 0.35, "cagr": 0.08,
    }
    return {
        "run_date": "2026-05-15",
        "parameters": {"universe_size": 100},
        "full_window": window,
        "pre_covid":   {**window, "sharpe": 0.9},
        "post_covid":  {**window, "sharpe": 0.75},
    }


def _write_strategy_files(base: Path, strategy: str) -> None:
    d = base / strategy
    d.mkdir(parents=True, exist_ok=True)
    _make_equity_df().to_csv(d / "equity_curve.csv", index=True, index_label="ts")
    _make_trades_df().to_csv(d / "trades.csv", index=False)
    with open(d / "metrics.json", "w") as fh:
        json.dump(_make_metrics_dict(), fh)


def _full_results() -> dict:
    return {
        "equity_curve": _make_equity_df(),
        "trades": _make_trades_df(),
        "metrics": _make_metrics_dict(),
    }


# ---------------------------------------------------------------------------
# load_strategy_results
# ---------------------------------------------------------------------------

class TestLoadStrategyResults:
    def test_returns_none_when_dir_missing(self, tmp_path):
        assert load_strategy_results("quant", tmp_path) is None

    def test_returns_none_when_equity_missing(self, tmp_path):
        d = tmp_path / "quant"
        d.mkdir()
        _make_trades_df().to_csv(d / "trades.csv", index=False)
        with open(d / "metrics.json", "w") as fh:
            json.dump({}, fh)
        assert load_strategy_results("quant", tmp_path) is None

    def test_returns_none_when_trades_missing(self, tmp_path):
        d = tmp_path / "quant"
        d.mkdir()
        _make_equity_df().to_csv(d / "equity_curve.csv", index_label="ts")
        with open(d / "metrics.json", "w") as fh:
            json.dump({}, fh)
        assert load_strategy_results("quant", tmp_path) is None

    def test_returns_none_when_metrics_missing(self, tmp_path):
        d = tmp_path / "quant"
        d.mkdir()
        _make_equity_df().to_csv(d / "equity_curve.csv", index_label="ts")
        _make_trades_df().to_csv(d / "trades.csv", index=False)
        assert load_strategy_results("quant", tmp_path) is None

    def test_returns_dict_when_all_files_present(self, tmp_path):
        _write_strategy_files(tmp_path, "quant")
        result = load_strategy_results("quant", tmp_path)
        assert result is not None
        assert set(result) == {"equity_curve", "trades", "metrics"}

    def test_equity_curve_has_equity_column(self, tmp_path):
        _write_strategy_files(tmp_path, "quant")
        result = load_strategy_results("quant", tmp_path)
        assert "equity" in result["equity_curve"].columns

    def test_equity_curve_has_datetime_index(self, tmp_path):
        _write_strategy_files(tmp_path, "quant")
        result = load_strategy_results("quant", tmp_path)
        assert pd.api.types.is_datetime64_any_dtype(result["equity_curve"].index)

    def test_trades_has_expected_columns(self, tmp_path):
        _write_strategy_files(tmp_path, "quant")
        result = load_strategy_results("quant", tmp_path)
        for col in ("symbol", "pnl", "holding_days"):
            assert col in result["trades"].columns

    def test_metrics_has_full_window(self, tmp_path):
        _write_strategy_files(tmp_path, "quant")
        result = load_strategy_results("quant", tmp_path)
        assert "full_window" in result["metrics"]

    def test_metrics_full_window_sharpe(self, tmp_path):
        _write_strategy_files(tmp_path, "quant")
        result = load_strategy_results("quant", tmp_path)
        assert abs(result["metrics"]["full_window"]["sharpe"] - 0.85) < 1e-9


# ---------------------------------------------------------------------------
# load_spy_results
# ---------------------------------------------------------------------------

class TestLoadSpyResults:
    def test_returns_none_when_missing(self, tmp_path):
        assert load_spy_results(tmp_path) is None

    def test_returns_none_when_quant_dir_missing(self, tmp_path):
        assert load_spy_results(tmp_path) is None

    def test_returns_dataframe_when_present(self, tmp_path):
        d = tmp_path / "quant"
        d.mkdir()
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        df = pd.DataFrame({"equity": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)
        df.index.name = "ts"
        df.to_csv(d / "spy_curve.csv")
        result = load_spy_results(tmp_path)
        assert result is not None
        assert "equity" in result.columns

    def test_spy_index_is_datetime(self, tmp_path):
        d = tmp_path / "quant"
        d.mkdir()
        idx = pd.date_range("2024-01-01", periods=3, freq="B")
        df = pd.DataFrame({"equity": [1.0, 1.1, 1.2]}, index=idx)
        df.index.name = "ts"
        df.to_csv(d / "spy_curve.csv")
        result = load_spy_results(tmp_path)
        assert pd.api.types.is_datetime64_any_dtype(result.index)


# ---------------------------------------------------------------------------
# normalise_equity
# ---------------------------------------------------------------------------

class TestNormaliseEquity:
    def test_first_value_equals_base(self):
        ec = _make_equity_df(n=5, initial=500_000.0)
        series = normalise_equity(ec, base=100.0)
        assert abs(float(series.iloc[0]) - 100.0) < 1e-9

    def test_returns_empty_for_empty_input(self):
        empty = pd.DataFrame({"equity": pd.Series(dtype=float)})
        result = normalise_equity(empty)
        assert result.empty

    def test_monotone_input_remains_monotone(self):
        ec = _make_equity_df(n=10, initial=1_000_000.0)
        series = normalise_equity(ec)
        assert (series.diff().dropna() >= 0).all()

    def test_custom_base_is_respected(self):
        ec = _make_equity_df(n=3, initial=200_000.0)
        series = normalise_equity(ec, base=1_000.0)
        assert abs(float(series.iloc[0]) - 1_000.0) < 1e-6

    def test_zero_initial_equity_returns_unchanged(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="B")
        ec = pd.DataFrame({"equity": [0.0, 1.0, 2.0]}, index=idx)
        result = normalise_equity(ec, base=100.0)
        # Should not raise and should return the raw values unchanged
        assert float(result.iloc[0]) == 0.0

    def test_relative_ratios_preserved(self):
        ec = _make_equity_df(n=3, initial=1_000.0)
        original_ratio = float(ec["equity"].iloc[2]) / float(ec["equity"].iloc[0])
        normed = normalise_equity(ec, base=100.0)
        normed_ratio = float(normed.iloc[2]) / float(normed.iloc[0])
        assert abs(original_ratio - normed_ratio) < 1e-9


# ---------------------------------------------------------------------------
# compute_drawdown_series
# ---------------------------------------------------------------------------

class TestComputeDrawdownSeries:
    def test_all_values_le_zero(self):
        ec = _make_equity_df(n=20)
        dd = compute_drawdown_series(ec)
        assert (dd <= 1e-12).all()  # small tolerance for floating-point equality at peak

    def test_monotone_increase_gives_zero_drawdown(self):
        ec = _make_equity_df(n=10)
        dd = compute_drawdown_series(ec)
        assert (dd.abs() < 1e-9).all()

    def test_drop_registers_negative_drawdown(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        eq = pd.Series([100.0, 110.0, 90.0, 95.0, 115.0], index=idx)
        ec = pd.DataFrame({"equity": eq, "cash": 0.0, "num_positions": 1})
        dd = compute_drawdown_series(ec)
        # Bar 2: 90 / 110 - 1 ≈ -0.182
        assert dd.iloc[2] < -0.1

    def test_full_recovery_restores_zero(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        eq = pd.Series([100.0, 110.0, 90.0, 95.0, 115.0], index=idx)
        ec = pd.DataFrame({"equity": eq, "cash": 0.0, "num_positions": 1})
        dd = compute_drawdown_series(ec)
        # Bar 4: 115 > 110 (old high), so drawdown = 0
        assert abs(dd.iloc[4]) < 1e-9

    def test_returns_series_with_same_index(self):
        ec = _make_equity_df(n=5)
        dd = compute_drawdown_series(ec)
        assert list(dd.index) == list(ec.index)


# ---------------------------------------------------------------------------
# format_metric_val
# ---------------------------------------------------------------------------

class TestFormatMetricVal:
    def test_none_returns_em_dash(self):
        assert format_metric_val(None, "sharpe") == "—"

    def test_nan_returns_em_dash(self):
        assert format_metric_val(float("nan"), "sharpe") == "—"

    def test_sharpe_three_decimal_places(self):
        assert format_metric_val(0.851234, "sharpe") == "0.851"

    def test_hit_rate_percentage(self):
        assert format_metric_val(0.1234, "hit_rate") == "12.3%"

    def test_max_drawdown_percentage(self):
        assert format_metric_val(0.2, "max_drawdown") == "20.0%"

    def test_trade_count_comma_separated(self):
        assert format_metric_val(1234, "trade_count") == "1,234"

    def test_trade_count_zero(self):
        assert format_metric_val(0, "trade_count") == "0"

    def test_win_loss_ratio_two_decimals(self):
        assert format_metric_val(1.754321, "win_loss_ratio") == "1.75"

    def test_unknown_metric_falls_back_gracefully(self):
        result = format_metric_val(42.5, "unknown_metric")
        assert "42" in result

    def test_avg_win_dollar_comma(self):
        result = format_metric_val(2500.0, "avg_win")
        assert result == "2,500"

    def test_cagr_percentage(self):
        assert format_metric_val(0.085, "cagr") == "8.5%"

    def test_total_return_percentage(self):
        assert format_metric_val(0.35, "total_return") == "35.0%"


# ---------------------------------------------------------------------------
# build_metrics_comparison
# ---------------------------------------------------------------------------

class TestBuildMetricsComparison:
    def test_returns_dataframe(self):
        all_results = {"quant": _full_results(), "vader": None}
        df = build_metrics_comparison(all_results)
        assert isinstance(df, pd.DataFrame)

    def test_columns_are_capitalised_strategy_names(self):
        all_results = {"quant": _full_results(), "vader": None}
        df = build_metrics_comparison(all_results)
        assert "Quant" in df.columns
        assert "Vader" in df.columns

    def test_none_strategy_gives_none_cells(self):
        all_results = {"quant": _full_results(), "vader": None}
        df = build_metrics_comparison(all_results)
        assert df.loc["Sharpe", "Vader"] is None

    def test_present_strategy_sharpe_value(self):
        all_results = {"quant": _full_results()}
        df = build_metrics_comparison(all_results)
        assert abs(float(df.loc["Sharpe", "Quant"]) - 0.85) < 1e-9

    def test_pre_covid_window_selects_correct_value(self):
        all_results = {"quant": _full_results()}
        df = build_metrics_comparison(all_results, window="pre_covid")
        assert abs(float(df.loc["Sharpe", "Quant"]) - 0.9) < 1e-9

    def test_post_covid_window_selects_correct_value(self):
        all_results = {"quant": _full_results()}
        df = build_metrics_comparison(all_results, window="post_covid")
        assert abs(float(df.loc["Sharpe", "Quant"]) - 0.75) < 1e-9

    def test_row_count_equals_metric_count(self):
        df = build_metrics_comparison({"quant": _full_results()})
        assert len(df) == len(METRIC_KEYS)

    def test_all_results_none_returns_all_none(self):
        all_results = {"quant": None, "vader": None}
        df = build_metrics_comparison(all_results)
        assert df["Quant"].isna().all() or (df["Quant"] == None).all()  # noqa: E711

    def test_hit_rate_metric_label(self):
        df = build_metrics_comparison({"quant": _full_results()})
        assert "Hit Rate" in df.index

    def test_exposure_metric_present(self):
        df = build_metrics_comparison({"quant": _full_results()})
        assert "% Time in Market" in df.index


# ---------------------------------------------------------------------------
# regime_sharpe_df
# ---------------------------------------------------------------------------

class TestRegimeSharpeDF:
    def test_returns_dataframe(self):
        df = regime_sharpe_df({"quant": _full_results(), "vader": None})
        assert isinstance(df, pd.DataFrame)

    def test_strategy_rows_present(self):
        df = regime_sharpe_df({"quant": _full_results(), "vader": None})
        assert "Quant" in df.index
        assert "Vader" in df.index

    def test_none_strategy_has_none_or_nan_values(self):
        import math
        df = regime_sharpe_df({"quant": _full_results(), "vader": None})
        # pandas may convert None → NaN in a mixed-type column; accept either
        for v in df.loc["Vader"].values:
            assert v is None or (isinstance(v, float) and math.isnan(v))

    def test_full_window_sharpe_value(self):
        df = regime_sharpe_df({"quant": _full_results()})
        full_col = WINDOW_LABELS["full_window"]
        assert abs(float(df.loc["Quant", full_col]) - 0.85) < 1e-9

    def test_pre_covid_sharpe_value(self):
        df = regime_sharpe_df({"quant": _full_results()})
        pre_col = WINDOW_LABELS["pre_covid"]
        assert abs(float(df.loc["Quant", pre_col]) - 0.9) < 1e-9

    def test_post_covid_sharpe_value(self):
        df = regime_sharpe_df({"quant": _full_results()})
        post_col = WINDOW_LABELS["post_covid"]
        assert abs(float(df.loc["Quant", post_col]) - 0.75) < 1e-9

    def test_columns_are_window_labels(self):
        df = regime_sharpe_df({"quant": _full_results()})
        for lbl in WINDOW_LABELS.values():
            assert lbl in df.columns

    def test_three_strategies_produces_three_rows(self):
        all_results = {
            "quant":   _full_results(),
            "vader":   None,
            "finbert": None,
        }
        df = regime_sharpe_df(all_results)
        assert len(df) == 3
