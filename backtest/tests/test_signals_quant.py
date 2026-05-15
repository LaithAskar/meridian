"""
Tests for backtest/signals/quant.py — QuantStrategy.

All tests are offline (no network I/O):
- Backend signal functions (momentum_signals, mean_reversion_signals) are
  exercised with synthetic DataFrames that are constructed to trigger known
  signal directions.
- QuantStrategy is exercised via on_bar loops over synthetic bar dicts.
  Since the Engine is not involved, the portfolio is never mutated between
  bars; tests that verify position-count logic therefore initialise the
  portfolio with the intended position state directly.

Synthetic data conventions
--------------------------
- Strong uptrend:    price × 1.005 per day (≈ +130 % over 100 days)
- Strong downtrend:  price × 0.995 per day
- Oversold crash:    price × 0.96  per day  (forces RSI < 25 within ~30 bars)
- Parabolic rally:   price × 1.04  per day  (forces RSI > 75 within ~20 bars)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.trading.quant.mean_reversion import mean_reversion_signals
from backend.trading.quant.momentum import momentum_signals
from backtest.signals.quant import QuantStrategy, _REGIME_WEIGHTS
from backtest.strategy import Order, Portfolio, Position, Strategy


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _ohlcv_df(prices: list[float], volume: float = 1_000_000.0) -> pd.DataFrame:
    """Build a capitalised-column OHLCV DataFrame from a list of close prices."""
    closes = np.asarray(prices, dtype=float)
    return pd.DataFrame(
        {
            "Close":  closes,
            "Open":   closes * 0.999,
            "High":   closes * 1.005,
            "Low":    closes * 0.995,
            "Volume": np.full(len(closes), volume),
        }
    )


def _bar(sym_prices: dict[str, float]) -> dict[str, pd.Series]:
    """Return one bar tick as {symbol: pd.Series(open/high/low/close/volume)}."""
    return {
        sym: pd.Series(
            {
                "open":   price * 0.999,
                "high":   price * 1.005,
                "low":    price * 0.995,
                "close":  price,
                "volume": 1_000_000.0,
            }
        )
        for sym, price in sym_prices.items()
    }


def _run(
    strat: QuantStrategy,
    sym_prices: dict[str, list[float]],
    portfolio: Portfolio | None = None,
    start: str = "2020-01-01",
) -> list[list[Order]]:
    """
    Feed *strat* with a price series for each symbol and collect per-bar orders.

    Uses a business-day date range so timestamps match realistic equity data.
    The portfolio is never mutated between bars (fills are the Engine's job).
    """
    n = max(len(v) for v in sym_prices.values())
    dates = pd.bdate_range(start, periods=n)
    pf = portfolio or Portfolio(cash=10_000_000.0)
    all_orders: list[list[Order]] = []
    for i, ts in enumerate(dates):
        bars = {
            sym: pd.Series(
                {
                    "open":   prices[i] * 0.999,
                    "high":   prices[i] * 1.005,
                    "low":    prices[i] * 0.995,
                    "close":  prices[i],
                    "volume": 1_000_000.0,
                }
            )
            for sym, prices in sym_prices.items()
            if i < len(prices)
        }
        all_orders.append(strat.on_bar(ts, bars, pf))
    return all_orders


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


class TestStructure:
    def test_is_strategy_subclass(self):
        assert issubclass(QuantStrategy, Strategy)

    def test_default_parameters(self):
        strat = QuantStrategy()
        assert strat.max_positions == 10
        assert strat._min_history_bars == 60
        assert strat._min_consensus == 0.55
        assert strat._spy_close is None
        assert strat._vix_close is None

    def test_custom_parameters_stored(self):
        spy = pd.Series([400.0], index=pd.DatetimeIndex(["2024-01-01"]))
        vix = pd.Series([15.0],  index=pd.DatetimeIndex(["2024-01-01"]))
        strat = QuantStrategy(
            max_positions=5,
            min_history_bars=30,
            spy_close=spy,
            vix_close=vix,
            min_consensus=0.6,
        )
        assert strat.max_positions == 5
        assert strat._min_history_bars == 30
        assert strat._min_consensus == 0.6
        assert strat._spy_close is spy
        assert strat._vix_close is vix


# ---------------------------------------------------------------------------
# History warm-up gate
# ---------------------------------------------------------------------------


class TestWarmUp:
    def test_returns_empty_before_min_history(self):
        """on_bar must return [] until min_history_bars bars have accumulated."""
        strat = QuantStrategy(min_history_bars=60)
        pf = Portfolio(cash=100_000.0)
        for i in range(59):
            ts = pd.Timestamp("2020-01-01") + pd.Timedelta(days=i)
            orders = strat.on_bar(ts, _bar({"AAPL": 100.0 + i, "MSFT": 200.0 + i}), pf)
            assert orders == [], f"Expected [] on bar {i}, got {orders}"

    def test_may_return_orders_after_min_history(self):
        """
        After warmup with min_consensus=0 (no filter), at least one bar after
        bar 60 must produce a non-empty order list given a strongly trending
        universe.
        """
        n = 80
        sym_prices = {
            "AAPL": [100.0 * (1.005 ** i) for i in range(n)],
            "MSFT": [100.0 * (0.997 ** i) for i in range(n)],
        }
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        all_orders = _run(strat, sym_prices)
        post_warmup = all_orders[60:]
        assert any(len(o) > 0 for o in post_warmup), (
            "Expected ≥1 non-empty order list after warmup with min_consensus=0.0"
        )


# ---------------------------------------------------------------------------
# Backend signal functions — unit tests on the underlying logic
# ---------------------------------------------------------------------------


class TestMomentumSignals:
    def test_uptrend_produces_buy(self):
        """
        Strong uptrend for TRENDING vs flat FLAT → TRENDING lands in the top
        quintile and receives a buy direction signal.
        """
        n = 100
        universe_data = {
            "TRENDING": _ohlcv_df([100.0 * (1.005 ** i) for i in range(n)]),
            "FLAT":     _ohlcv_df([100.0] * n),
        }
        sigs = {s["ticker"]: s for s in momentum_signals(universe_data)}
        assert "TRENDING" in sigs, "Expected a signal for TRENDING"
        assert sigs["TRENDING"]["direction"] == "buy"

    def test_downtrend_produces_sell(self):
        n = 100
        universe_data = {
            "DOWN": _ohlcv_df([100.0 * (0.995 ** i) for i in range(n)]),
            "FLAT": _ohlcv_df([100.0] * n),
        }
        sigs = {s["ticker"]: s for s in momentum_signals(universe_data)}
        assert "DOWN" in sigs, "Expected a signal for DOWN"
        assert sigs["DOWN"]["direction"] == "sell"

    def test_too_few_bars_produces_no_signal(self):
        """momentum_signals requires ≥ 60 bars; it silently skips shorter series."""
        universe_data = {"SHORT": _ohlcv_df([100.0] * 30)}
        sigs = momentum_signals(universe_data)
        assert all(s["ticker"] != "SHORT" for s in sigs)

    def test_score_within_plausible_range(self):
        n = 100
        universe_data = {
            "A": _ohlcv_df([100.0 * (1.003 ** i) for i in range(n)]),
            "B": _ohlcv_df([100.0 * (0.997 ** i) for i in range(n)]),
        }
        for sig in momentum_signals(universe_data):
            assert -1.0 <= sig["score"] <= 1.0, f"Score out of range: {sig['score']}"


class TestMeanReversionSignals:
    def test_sharp_decline_produces_buy(self):
        """
        Accelerating decline forces RSI < 25, price below BB lower band, and
        z-score < -2 → all three sub-scores add up to a buy signal.
        """
        n = 60
        prices = [100.0 * (0.96 ** i) for i in range(n)]
        sigs = {s["ticker"]: s for s in mean_reversion_signals({"CRASH": _ohlcv_df(prices)})}
        assert "CRASH" in sigs, "Expected a buy signal for the crashing ticker"
        assert sigs["CRASH"]["direction"] == "buy"

    def test_spike_above_bb_produces_sell(self):
        """
        55 bars flat at 100 then 5 bars of +20%/day: current blows through the
        BB upper band (price >> SMA20 + 2σ) and z-score > 2 → sell signal.

        A pure monotone uptrend does NOT trigger this because the BB bands
        widen with the trend and RSI returns 50 (no losses → division-by-zero
        → fillna(50)).  The flat-then-spike pattern isolates the "price is
        extreme relative to recent history" condition that mean-reversion
        actually tests.
        """
        flat = [100.0] * 55
        spike = [100.0 * (1.20 ** i) for i in range(1, 6)]   # 5 bars: +20%/bar
        prices = flat + spike                                   # price ≈ 249 by end
        sigs = {s["ticker"]: s for s in mean_reversion_signals({"SPIKE": _ohlcv_df(prices)})}
        assert "SPIKE" in sigs, "Expected a sell signal for the spike ticker"
        assert sigs["SPIKE"]["direction"] == "sell"

    def test_too_few_bars_produces_no_signal(self):
        universe_data = {"SHORT": _ohlcv_df([100.0] * 20)}
        sigs = mean_reversion_signals(universe_data)
        assert all(s["ticker"] != "SHORT" for s in sigs)


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------


class TestRegimeDetection:
    def test_defaults_to_neutral_without_spy(self):
        strat = QuantStrategy()
        info = strat._regime_at(pd.Timestamp("2024-01-01"))
        assert info["regime"] == "neutral"
        assert info["strategyWeights"] == _REGIME_WEIGHTS["neutral"]

    def test_bull_trend_regime(self):
        """
        252 bars of steady 0.1 %/day uptrend: SPY current > SMA50 > SMA200
        with VIX = 15 → bull_trend.
        """
        n = 252
        idx = pd.bdate_range("2019-01-01", periods=n)
        spy = pd.Series([100.0 * (1.001 ** i) for i in range(n)], index=idx)
        vix = pd.Series([15.0] * n, index=idx)
        strat = QuantStrategy(spy_close=spy, vix_close=vix)
        info = strat._regime_at(idx[-1])
        assert info["regime"] == "bull_trend"
        assert info["strategyWeights"] == _REGIME_WEIGHTS["bull_trend"]

    def test_bear_trend_regime(self):
        n = 252
        idx = pd.bdate_range("2022-01-01", periods=n)
        spy = pd.Series([400.0 * (0.999 ** i) for i in range(n)], index=idx)
        vix = pd.Series([20.0] * n, index=idx)
        strat = QuantStrategy(spy_close=spy, vix_close=vix)
        info = strat._regime_at(idx[-1])
        assert info["regime"] == "bear_trend"

    def test_crisis_regime_from_high_vix(self):
        """VIX > 30 overrides any SPY trend and forces crisis regime."""
        n = 60
        idx = pd.bdate_range("2020-03-01", periods=n)
        spy = pd.Series([300.0] * n, index=idx)
        vix = pd.Series([40.0] * n, index=idx)
        strat = QuantStrategy(spy_close=spy, vix_close=vix)
        info = strat._regime_at(idx[-1])
        assert info["regime"] == "crisis"

    def test_high_volatility_regime(self):
        """VIX between 22 and 30 → high_volatility."""
        n = 60
        idx = pd.bdate_range("2020-01-01", periods=n)
        spy = pd.Series([300.0] * n, index=idx)
        vix = pd.Series([25.0] * n, index=idx)
        strat = QuantStrategy(spy_close=spy, vix_close=vix)
        info = strat._regime_at(idx[-1])
        assert info["regime"] == "high_volatility"

    def test_regime_uses_only_data_up_to_ts(self):
        """
        At ts = day 99 we should be in a bearish/neutral regime because the
        first 100 days trend down; only after day 100 does price rocket up.
        The _regime_at call for day 99 must NOT see day 100+ prices.
        """
        n = 252
        idx = pd.bdate_range("2019-01-01", periods=n)
        down = [100.0 * (0.998 ** i) for i in range(100)]
        up = [down[-1] * (1.003 ** (i + 1)) for i in range(152)]
        spy = pd.Series(down + up, index=idx)
        vix = pd.Series([18.0] * n, index=idx)
        strat = QuantStrategy(spy_close=spy, vix_close=vix)

        info_early = strat._regime_at(idx[99])
        # Can be neutral or bear depending on how far SMA50/200 have decayed
        assert info_early["regime"] in ("bear_trend", "neutral", "high_volatility")

        info_late = strat._regime_at(idx[-1])
        assert info_late["regime"] in ("bull_trend", "neutral")

    def test_all_regime_keys_exist(self):
        assert set(_REGIME_WEIGHTS) == {
            "crisis", "high_volatility", "bull_trend", "bear_trend", "neutral"
        }
        for regime, w in _REGIME_WEIGHTS.items():
            assert "momentum" in w and "mean_reversion" in w and "factor" in w, regime
            assert w["factor"] == 0.0, f"Factor weight must be zero; regime={regime}"


# ---------------------------------------------------------------------------
# Order generation and position sizing
# ---------------------------------------------------------------------------


class TestOrderGeneration:
    def test_all_orders_have_positive_qty(self):
        n = 80
        sym_prices = {
            "AAPL": [100.0 * (1.003 ** i) for i in range(n)],
            "MSFT": [200.0 * (0.997 ** i) for i in range(n)],
        }
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        for bar_orders in _run(strat, sym_prices):
            for o in bar_orders:
                assert o.qty > 0, f"Order qty must be positive: {o}"

    def test_order_sides_are_valid(self):
        n = 80
        sym_prices = {
            "AAPL": [100.0 * (1.003 ** i) for i in range(n)],
            "MSFT": [200.0 * (0.997 ** i) for i in range(n)],
        }
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        for bar_orders in _run(strat, sym_prices):
            for o in bar_orders:
                assert o.side in ("buy", "sell"), f"Invalid side: {o.side}"

    def test_no_sell_when_portfolio_empty(self):
        """
        Strategy must not issue a sell for a symbol it doesn't hold.
        Use a crashing ticker which will generate a sell signal from
        mean-reversion once the aggregate confirms it — but with an empty
        portfolio the sell loop body is never entered.
        """
        n = 80
        # Parabolic rally → momentum buy + mean-reversion sell → conflicting;
        # but with min_consensus=0.0 the tie resolves to sell.
        sym_prices = {
            "RALLY": [100.0 * (1.04 ** i) for i in range(n)],
            "FLAT":  [100.0] * n,
        }
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        pf = Portfolio(cash=1_000_000.0)  # no positions
        dates = pd.bdate_range("2020-01-01", periods=n)
        for i, ts in enumerate(dates):
            bars = {
                sym: pd.Series(
                    {
                        "open":   sym_prices[sym][i] * 0.999,
                        "high":   sym_prices[sym][i] * 1.005,
                        "low":    sym_prices[sym][i] * 0.995,
                        "close":  sym_prices[sym][i],
                        "volume": 1_000_000.0,
                    }
                )
                for sym in sym_prices
            }
            orders = strat.on_bar(ts, bars, pf)
            sells = [o for o in orders if o.side == "sell"]
            assert sells == [], f"Bar {i}: unexpected sell on empty portfolio: {sells}"

    def test_max_positions_per_bar_not_exceeded(self):
        """
        With 6 identically trending symbols and max_positions=3, the strategy
        must not issue more than 3 buys on any single bar.

        The portfolio starts empty and is never mutated between bars, so
        portfolio.num_positions == 0 throughout.  The strategy uses this to
        calculate open_slots = max_positions - 0 = 3.
        """
        n = 80
        syms = ["A", "B", "C", "D", "E", "F"]
        sym_prices = {sym: [100.0 * (1.004 ** i) for i in range(n)] for sym in syms}

        strat = QuantStrategy(max_positions=3, min_history_bars=60, min_consensus=0.0)
        pf = Portfolio(cash=50_000_000.0)
        dates = pd.bdate_range("2020-01-01", periods=n)

        for i, ts in enumerate(dates):
            bars = {
                sym: pd.Series(
                    {
                        "open":   sym_prices[sym][i] * 0.999,
                        "high":   sym_prices[sym][i] * 1.005,
                        "low":    sym_prices[sym][i] * 0.995,
                        "close":  sym_prices[sym][i],
                        "volume": 1_000_000.0,
                    }
                )
                for sym in syms
            }
            orders = strat.on_bar(ts, bars, pf)
            buy_count = sum(1 for o in orders if o.side == "buy")
            # With empty portfolio (no positions, no sells), buys ≤ max_positions
            assert buy_count <= strat.max_positions, (
                f"Bar {i}: issued {buy_count} buys, max_positions={strat.max_positions}"
            )

    def test_no_double_buy_for_held_symbol(self):
        """
        If AAPL is already in the portfolio, the strategy must not issue
        another buy for it regardless of how strong the signal is.
        """
        n = 80
        sym_prices = {"AAPL": [100.0 * (1.004 ** i) for i in range(n)]}
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        pf = Portfolio(
            cash=1_000_000.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        dates = pd.bdate_range("2020-01-01", periods=n)
        for i, ts in enumerate(dates):
            bars = {
                "AAPL": pd.Series(
                    {
                        "open":   sym_prices["AAPL"][i] * 0.999,
                        "high":   sym_prices["AAPL"][i] * 1.005,
                        "low":    sym_prices["AAPL"][i] * 0.995,
                        "close":  sym_prices["AAPL"][i],
                        "volume": 1_000_000.0,
                    }
                )
            }
            orders = strat.on_bar(ts, bars, pf)
            aapl_buys = [o for o in orders if o.side == "buy" and o.symbol == "AAPL"]
            assert aapl_buys == [], (
                f"Bar {i}: should not buy AAPL when already holding it"
            )

    def test_sell_issued_for_held_position_with_sell_signal(self):
        """
        If the portfolio holds AAPL and the aggregate signal is sell, the
        strategy must issue a sell order for the full held quantity.

        Price series: 55 bars flat then 5-bar spike (+20%/bar).  After bar 60
        the mean-reversion score is -0.55 (BB above upper + z-score > 2),
        which aggregates to a sell direction.  With min_consensus=0.0 no
        consensus filter is applied.

        Note: a pure monotone uptrend does NOT reliably trigger a sell because
        compute_rsi returns 50.0 on all-positive series (no losses →
        division-by-zero → fillna(50)).
        """
        # Build an 80-bar series: flat up to bar 55, then spike for 5 bars,
        # then flatten again.  The spike window (bars 55-59) triggers the
        # mean-reversion sell signal at bar 60.
        flat_pre  = [100.0] * 55
        spike     = [100.0 * (1.20 ** i) for i in range(1, 6)]   # bars 55-59
        flat_post = [spike[-1]] * (80 - 60)                       # bars 60-79 flat
        aapl_prices = flat_pre + spike + flat_post

        sym_prices = {
            "AAPL": aapl_prices,
            "FLAT": [100.0] * 80,
        }
        pf = Portfolio(
            cash=500_000.0,
            positions={"AAPL": Position("AAPL", qty=50.0, avg_cost=100.0)},
        )
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        dates = pd.bdate_range("2020-01-01", periods=80)

        found_sell = False
        for i, ts in enumerate(dates):
            bars = {
                sym: pd.Series(
                    {
                        "open":   sym_prices[sym][i] * 0.999,
                        "high":   sym_prices[sym][i] * 1.005,
                        "low":    sym_prices[sym][i] * 0.995,
                        "close":  sym_prices[sym][i],
                        "volume": 1_000_000.0,
                    }
                )
                for sym in sym_prices
            }
            orders = strat.on_bar(ts, bars, pf)
            for o in orders:
                if o.side == "sell" and o.symbol == "AAPL":
                    assert o.qty == pytest.approx(50.0), (
                        f"Sell qty should be full position (50); got {o.qty}"
                    )
                    found_sell = True

        assert found_sell, (
            "Expected at least one sell order for AAPL: flat-then-spike pattern "
            "should trigger mean-reversion sell, but none was issued"
        )

    def test_buy_respects_available_cash(self):
        """
        With very little cash and high prices, qty = floor(target/price) may be
        0 → the buy is skipped.  No order should be issued if cash is
        insufficient for even 1 share.
        """
        n = 80
        # High price relative to cash
        sym_prices = {
            "AAPL": [50_000.0 * (1.003 ** i) for i in range(n)],
            "MSFT": [100.0 * (0.997 ** i) for i in range(n)],
        }
        # max_positions=5 → target_per_slot = 1_000 / 5 = 200 per slot
        # AAPL price ≈ 50_000 → qty = floor(200 / 50_000) = 0 → skipped
        pf = Portfolio(cash=1_000.0)
        strat = QuantStrategy(min_history_bars=60, max_positions=5, min_consensus=0.0)
        all_orders = _run(strat, sym_prices, portfolio=pf)
        for bar_orders in all_orders:
            for o in bar_orders:
                if o.side == "buy" and o.symbol == "AAPL":
                    pytest.fail(
                        f"Should not buy AAPL at ~$50,000 with only $1,000 available"
                    )
