"""
Tests for backtest/engine.py — Engine event loop, portfolio accounting, and trade records.

All tests monkeypatch fetch_bars so no network or disk I/O occurs.

Synthetic bar layout
--------------------
_make_bars({symbol: [close_day0, close_day1, ...]}, start_date)

open  = close × 0.99   (slightly below close — ensures slippage arithmetic
                         produces clean, predictable fill prices)
high  = close × 1.01
low   = close × 0.98
close = as specified
volume = 10_000

Timestamps are NYSE business days starting at start_date.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import backtest.engine as _engine_mod
from backtest.engine import BacktestResult, Engine, _apply_fill, _bars_at
from backtest.fills import SLIPPAGE_BPS
from backtest.strategy import Order, Portfolio, Position, Strategy


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

START = date(2024, 1, 2)  # first NYSE trading day of 2024


def _make_bars(
    symbols_prices: dict[str, list[float]],
    start: date = START,
) -> pd.DataFrame:
    """Build a synthetic MultiIndex (symbol, date) DataFrame from close prices."""
    n_max = max(len(v) for v in symbols_prices.values())
    dates = pd.bdate_range(start=start, periods=n_max)

    frames: list[pd.DataFrame] = []
    for sym, prices in symbols_prices.items():
        n = len(prices)
        df = pd.DataFrame(
            {
                "open":   [p * 0.99 for p in prices],
                "high":   [p * 1.01 for p in prices],
                "low":    [p * 0.98 for p in prices],
                "close":  prices,
                "volume": [10_000] * n,
            },
            index=pd.MultiIndex.from_tuples(
                [(sym, d) for d in dates[:n]],
                names=["symbol", "date"],
            ),
        )
        frames.append(df)

    return pd.concat(frames).sort_index()


def _patch_fetch(monkeypatch, bars: pd.DataFrame) -> None:
    """Replace fetch_bars in the engine module with a lambda returning *bars*."""
    monkeypatch.setattr(_engine_mod, "fetch_bars", lambda *a, **kw: bars)


# ---------------------------------------------------------------------------
# Concrete strategy helpers
# ---------------------------------------------------------------------------

class NoopStrategy(Strategy):
    """Always returns [] — used as the zero-signal baseline."""

    def on_bar(self, ts, bars, portfolio) -> list[Order]:
        return []


class BuyOnFirstBarStrategy(Strategy):
    """
    Buys *qty* shares of *symbol* on the very first bar it sees, then holds.
    Used to verify next-bar-open fill timing.
    """

    def __init__(self, symbol: str, qty: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symbol = symbol
        self.qty = qty
        self._fired = False

    def on_bar(self, ts, bars, portfolio) -> list[Order]:
        if not self._fired and self.symbol in bars:
            self._fired = True
            return [Order(symbol=self.symbol, side="buy", qty=self.qty)]
        return []


class BuyThenSellStrategy(Strategy):
    """
    Buys *qty* shares on bar index *buy_bar*, sells on bar index *sell_bar*.
    Bar index counts from 0 = first bar the engine processes.
    """

    def __init__(self, symbol: str, qty: float, buy_bar: int, sell_bar: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symbol = symbol
        self.qty = qty
        self.buy_bar = buy_bar
        self.sell_bar = sell_bar
        self._bar_count = 0

    def on_bar(self, ts, bars, portfolio) -> list[Order]:
        i = self._bar_count
        self._bar_count += 1

        if i == self.buy_bar and self.symbol in bars:
            return [Order(symbol=self.symbol, side="buy", qty=self.qty)]
        if i == self.sell_bar and self.symbol in bars:
            return [Order(symbol=self.symbol, side="sell", qty=self.qty)]
        return []


# ---------------------------------------------------------------------------
# NoopStrategy — equity and shape invariants
# ---------------------------------------------------------------------------

class TestNoopEngine:
    def test_equity_stays_at_initial_cash(self, monkeypatch):
        """With no trades, equity must equal the starting NAV every day."""
        bars = _make_bars({"AAPL": [150.0] * 20, "MSFT": [300.0] * 20})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            strategy=NoopStrategy(),
            universe=["AAPL", "MSFT"],
            start=START,
            end=START + timedelta(days=30),
            initial_cash=100_000.0,
        ).run()

        assert isinstance(result, BacktestResult)
        assert (result.equity_curve["equity"] == 100_000.0).all(), (
            "Equity drifted despite NoopStrategy"
        )

    def test_no_nan_in_equity_curve(self, monkeypatch):
        bars = _make_bars({"AAPL": [150.0] * 20, "MSFT": [300.0] * 20})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            strategy=NoopStrategy(),
            universe=["AAPL", "MSFT"],
            start=START,
            end=START + timedelta(days=30),
            initial_cash=100_000.0,
        ).run()

        assert not result.equity_curve.isnull().any().any(), "NaN found in equity curve"

    def test_equity_curve_row_count(self, monkeypatch):
        """One row per trading day in the synthetic bar set."""
        n_days = 15
        bars = _make_bars({"AAPL": [100.0] * n_days})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            strategy=NoopStrategy(),
            universe=["AAPL"],
            start=START,
            end=START + timedelta(days=30),
        ).run()

        assert len(result.equity_curve) == n_days

    def test_equity_curve_columns(self, monkeypatch):
        bars = _make_bars({"AAPL": [100.0] * 5})
        _patch_fetch(monkeypatch, bars)

        result = Engine(NoopStrategy(), ["AAPL"], START, START + timedelta(days=10)).run()

        assert set(result.equity_curve.columns) >= {"equity", "cash", "num_positions"}

    def test_num_positions_zero_throughout(self, monkeypatch):
        bars = _make_bars({"AAPL": [100.0] * 10})
        _patch_fetch(monkeypatch, bars)

        result = Engine(NoopStrategy(), ["AAPL"], START, START + timedelta(days=15)).run()

        assert (result.equity_curve["num_positions"] == 0).all()

    def test_empty_trades_with_noop(self, monkeypatch):
        bars = _make_bars({"AAPL": [100.0] * 5})
        _patch_fetch(monkeypatch, bars)

        result = Engine(NoopStrategy(), ["AAPL"], START, START + timedelta(days=10)).run()

        assert result.trades.empty


# ---------------------------------------------------------------------------
# Fill timing — orders placed on bar T fill at bar T+1
# ---------------------------------------------------------------------------

class TestFillTiming:
    def test_buy_fills_at_next_bar_open(self, monkeypatch):
        """
        Strategy buys on bar 0.  Fill must land at bar 1's open price.
        Bar 0 open = 100 × 0.99 = 99.00;  bar 1 open = 110 × 0.99 = 108.90.
        Expected fill = 108.90 × (1 + 5e-4) = 108.9545.
        """
        bars = _make_bars({"AAPL": [100.0, 110.0, 110.0, 110.0, 110.0]})
        _patch_fetch(monkeypatch, bars)

        received: list[Portfolio] = []

        class InspectStrategy(Strategy):
            _bar = 0

            def on_bar(self, ts, bars_t, portfolio):
                received.append(portfolio)
                if self._bar == 0:
                    self._bar += 1
                    return [Order("AAPL", "buy", 10.0)]
                self._bar += 1
                return []

        result = Engine(InspectStrategy(), ["AAPL"], START, START + timedelta(days=20)).run()

        # Bar 0 snapshot: no fills yet (fill happens at bar 1's open)
        # → equity == initial_cash == 1_000_000
        assert result.equity_curve["equity"].iloc[0] == pytest.approx(1_000_000.0)

        # Bar 1 snapshot: fill has been applied at bar 1's open
        # cash = 1_000_000 - 10 × 108.9545 = 1_000_000 - 1_089.545 = 998_910.455
        # equity = cash + 10 × 110.0 (close) = 998_910.455 + 1_100 = 1_000_010.455
        bar1_open = 110.0 * 0.99
        expected_fill_price = bar1_open * (1 + SLIPPAGE_BPS * 1e-4)
        expected_cash = 1_000_000.0 - 10.0 * expected_fill_price
        expected_equity = expected_cash + 10.0 * 110.0  # marked at close
        assert result.equity_curve["equity"].iloc[1] == pytest.approx(expected_equity, rel=1e-6)

    def test_no_fill_on_last_bar(self, monkeypatch):
        """
        Orders submitted on the final bar have no next bar to fill at.
        They should be silently dropped — no crash, equity unchanged.
        """
        bars = _make_bars({"AAPL": [100.0, 100.0, 100.0]})
        _patch_fetch(monkeypatch, bars)

        class BuyLastBarStrategy(Strategy):
            _bar = 0
            _n = 3

            def on_bar(self, ts, bars_t, portfolio):
                self._bar += 1
                if self._bar == self._n:  # last bar
                    return [Order("AAPL", "buy", 5.0)]
                return []

        result = Engine(
            BuyLastBarStrategy(), ["AAPL"], START, START + timedelta(days=10)
        ).run()

        # equity must stay at initial_cash throughout (order never fills)
        assert (result.equity_curve["equity"] == 1_000_000.0).all()


# ---------------------------------------------------------------------------
# Portfolio accounting — buy then hold
# ---------------------------------------------------------------------------

class TestBuyAndHold:
    def test_cash_decreases_after_buy_fill(self, monkeypatch):
        """After a buy fill, cash must be reduced by qty × fill_price."""
        bars = _make_bars({"AAPL": [100.0, 110.0, 120.0, 130.0, 140.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyOnFirstBarStrategy("AAPL", 10.0),
            ["AAPL"],
            START,
            START + timedelta(days=20),
            initial_cash=1_000_000.0,
        ).run()

        # Fill at bar 1's open = 110 × 0.99 × (1 + 5bps)
        bar1_open = 110.0 * 0.99
        fill_price = bar1_open * (1 + SLIPPAGE_BPS * 1e-4)
        expected_cash = 1_000_000.0 - 10.0 * fill_price

        # Cash reported on bar 1 (after fill applied)
        assert result.equity_curve["cash"].iloc[1] == pytest.approx(expected_cash, rel=1e-6)

    def test_position_count_increments_after_buy(self, monkeypatch):
        bars = _make_bars({"AAPL": [100.0, 110.0, 120.0, 130.0, 140.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyOnFirstBarStrategy("AAPL", 10.0),
            ["AAPL"],
            START,
            START + timedelta(days=20),
        ).run()

        assert result.equity_curve["num_positions"].iloc[0] == 0  # pre-fill
        assert result.equity_curve["num_positions"].iloc[1] == 1  # post-fill

    def test_equity_tracks_stock_price_after_buy(self, monkeypatch):
        """After the buy fills, equity = cash + qty × close_price each day."""
        closes = [100.0, 110.0, 130.0, 90.0, 150.0]
        bars = _make_bars({"AAPL": closes})
        _patch_fetch(monkeypatch, bars)

        initial_cash = 1_000_000.0
        qty = 10.0
        result = Engine(
            BuyOnFirstBarStrategy("AAPL", qty),
            ["AAPL"],
            START,
            START + timedelta(days=20),
            initial_cash=initial_cash,
        ).run()

        bar1_open = closes[1] * 0.99
        fill_price = bar1_open * (1 + SLIPPAGE_BPS * 1e-4)
        cash_after_buy = initial_cash - qty * fill_price

        for i, close in enumerate(closes[1:], start=1):
            expected_eq = cash_after_buy + qty * close
            assert result.equity_curve["equity"].iloc[i] == pytest.approx(
                expected_eq, rel=1e-6
            ), f"Equity mismatch on bar {i}"


# ---------------------------------------------------------------------------
# Trade records — buy then sell
# ---------------------------------------------------------------------------

class TestTradeRecords:
    def test_trade_recorded_on_sell(self, monkeypatch):
        """A buy on bar 0 and sell on bar 2 should produce one closed trade."""
        bars = _make_bars({"AAPL": [100.0, 110.0, 120.0, 130.0, 140.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyThenSellStrategy("AAPL", qty=5.0, buy_bar=0, sell_bar=2),
            ["AAPL"],
            START,
            START + timedelta(days=20),
        ).run()

        assert len(result.trades) == 1
        t = result.trades.iloc[0]
        assert t["symbol"] == "AAPL"
        assert t["qty"] == pytest.approx(5.0)

    def test_trade_pnl_sign_profitable(self, monkeypatch):
        """Buy at a low price, sell at a high price → positive P&L."""
        bars = _make_bars({"AAPL": [100.0, 200.0, 300.0, 300.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyThenSellStrategy("AAPL", qty=10.0, buy_bar=0, sell_bar=2),
            ["AAPL"],
            START,
            START + timedelta(days=20),
        ).run()

        assert result.trades.iloc[0]["pnl"] > 0

    def test_trade_pnl_sign_loss(self, monkeypatch):
        """Buy high, sell low → negative P&L."""
        bars = _make_bars({"AAPL": [300.0, 200.0, 100.0, 100.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyThenSellStrategy("AAPL", qty=10.0, buy_bar=0, sell_bar=2),
            ["AAPL"],
            START,
            START + timedelta(days=20),
        ).run()

        assert result.trades.iloc[0]["pnl"] < 0

    def test_trade_pnl_value(self, monkeypatch):
        """Verify exact P&L arithmetic end-to-end through fills + slippage."""
        bars = _make_bars({"AAPL": [100.0, 100.0, 200.0, 200.0]})
        _patch_fetch(monkeypatch, bars)

        qty = 10.0
        result = Engine(
            BuyThenSellStrategy("AAPL", qty=qty, buy_bar=0, sell_bar=2),
            ["AAPL"],
            START,
            START + timedelta(days=20),
        ).run()

        # Fill at bar 1 open = 100 × 0.99 = 99.00;  buy price = 99.00 × (1 + 5bps)
        entry_fill = (100.0 * 0.99) * (1 + SLIPPAGE_BPS * 1e-4)
        # Fill at bar 3 open = 200 × 0.99 = 198.00; sell price = 198.00 × (1 - 5bps)
        exit_fill = (200.0 * 0.99) * (1 - SLIPPAGE_BPS * 1e-4)
        expected_pnl = (exit_fill - entry_fill) * qty

        assert result.trades.iloc[0]["pnl"] == pytest.approx(expected_pnl, rel=1e-6)

    def test_holding_days_positive(self, monkeypatch):
        bars = _make_bars({"AAPL": [100.0, 100.0, 100.0, 100.0, 100.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyThenSellStrategy("AAPL", qty=1.0, buy_bar=0, sell_bar=3),
            ["AAPL"],
            START,
            START + timedelta(days=20),
        ).run()

        assert result.trades.iloc[0]["holding_days"] >= 0

    def test_no_trades_without_sell(self, monkeypatch):
        """A buy with no subsequent sell produces no closed trades."""
        bars = _make_bars({"AAPL": [100.0, 110.0, 120.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyOnFirstBarStrategy("AAPL", 5.0),
            ["AAPL"],
            START,
            START + timedelta(days=10),
        ).run()

        assert result.trades.empty


# ---------------------------------------------------------------------------
# Sell-cap — cannot sell more than held
# ---------------------------------------------------------------------------

class TestSellCap:
    def test_sell_capped_at_held_qty(self, monkeypatch):
        """
        Selling 100 shares when only 10 are held should close exactly 10 shares.
        The trade record's qty must be 10, not 100.
        """
        bars = _make_bars({"AAPL": [100.0, 100.0, 150.0, 150.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyThenSellStrategy("AAPL", qty=100.0, buy_bar=0, sell_bar=2),
            ["AAPL"],
            START,
            START + timedelta(days=20),
            initial_cash=1_000_000.0,
        ).run()

        # The buy order was for 100 shares — that fills fine (cash is ample)
        # The sell order is capped at 100 held shares (which is exactly what was bought)
        assert result.trades.iloc[0]["qty"] == pytest.approx(100.0)

    def test_sell_with_no_position_is_noop(self, monkeypatch):
        """Selling a symbol the portfolio doesn't hold produces no trade record."""
        bars = _make_bars({"AAPL": [100.0, 100.0, 100.0]})
        _patch_fetch(monkeypatch, bars)

        class SellWithNothingStrategy(Strategy):
            def on_bar(self, ts, bars_t, portfolio):
                if "AAPL" in bars_t:
                    return [Order("AAPL", "sell", 10.0)]
                return []

        result = Engine(
            SellWithNothingStrategy(),
            ["AAPL"],
            START,
            START + timedelta(days=10),
        ).run()

        assert result.trades.empty
        # equity never changes (no position to close)
        assert (result.equity_curve["equity"] == 1_000_000.0).all()


# ---------------------------------------------------------------------------
# Delisted / missing bar handling
# ---------------------------------------------------------------------------

class TestDelistedHandling:
    def test_order_cancelled_when_symbol_has_no_next_bar(self, monkeypatch):
        """
        Strategy buys AAPL on bar 0.  AAPL has data only for bar 0 (delisted).
        The pending order should be silently cancelled — no crash, no fill.
        """
        # Only one bar of data
        bars = _make_bars({"AAPL": [100.0]})
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            BuyOnFirstBarStrategy("AAPL", 10.0),
            ["AAPL"],
            START,
            START + timedelta(days=10),
        ).run()

        # Only one snapshot row (only one bar of data)
        assert len(result.equity_curve) == 1
        # Order placed on bar 0 has no bar 1 to fill at → cancelled
        assert result.equity_curve["equity"].iloc[0] == pytest.approx(1_000_000.0)
        assert result.trades.empty

    def test_symbol_with_gaps_does_not_crash(self, monkeypatch):
        """
        AAPL has 5 bars; MSFT only 3.  Engine must process without crashing.
        """
        aapl_dates = pd.bdate_range(start=START, periods=5)
        msft_dates = pd.bdate_range(start=START, periods=3)

        aapl_df = pd.DataFrame(
            {"open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 10_000},
            index=pd.MultiIndex.from_tuples(
                [("AAPL", d) for d in aapl_dates], names=["symbol", "date"]
            ),
        )
        msft_df = pd.DataFrame(
            {"open": 297.0, "high": 303.0, "low": 294.0, "close": 300.0, "volume": 5_000},
            index=pd.MultiIndex.from_tuples(
                [("MSFT", d) for d in msft_dates], names=["symbol", "date"]
            ),
        )
        bars = pd.concat([aapl_df, msft_df]).sort_index()
        _patch_fetch(monkeypatch, bars)

        result = Engine(
            NoopStrategy(),
            ["AAPL", "MSFT"],
            START,
            START + timedelta(days=15),
        ).run()

        # Five unique timestamps → five equity rows
        assert len(result.equity_curve) == 5
        assert not result.equity_curve.isnull().any().any()


# ---------------------------------------------------------------------------
# Empty universe / empty bars
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_bars_returns_empty_result(self, monkeypatch):
        """When fetch_bars returns an empty DataFrame, run() returns empty results."""
        _patch_fetch(monkeypatch, pd.DataFrame())

        result = Engine(NoopStrategy(), [], START, START + timedelta(days=10)).run()

        assert result.equity_curve.empty
        assert result.trades.empty

    def test_result_index_is_datetime(self, monkeypatch):
        bars = _make_bars({"AAPL": [100.0] * 5})
        _patch_fetch(monkeypatch, bars)

        result = Engine(NoopStrategy(), ["AAPL"], START, START + timedelta(days=10)).run()

        assert isinstance(result.equity_curve.index, pd.DatetimeIndex)


# ---------------------------------------------------------------------------
# _apply_fill unit tests (lower-level, covers accounting edge cases)
# ---------------------------------------------------------------------------

class TestApplyFill:
    """Direct unit tests for the _apply_fill helper."""

    def _make_buy_fill(self, symbol="AAPL", qty=10.0, price=100.0):
        from backtest.fills import Fill
        return Fill(
            ts=pd.Timestamp("2024-01-02"),
            symbol=symbol,
            side="buy",
            qty=qty,
            fill_price=price,
        )

    def _make_sell_fill(self, symbol="AAPL", qty=10.0, price=150.0):
        from backtest.fills import Fill
        return Fill(
            ts=pd.Timestamp("2024-01-05"),
            symbol=symbol,
            side="sell",
            qty=qty,
            fill_price=price,
        )

    def test_buy_reduces_cash(self):
        pf = Portfolio(cash=10_000.0)
        _apply_fill(pf, self._make_buy_fill(qty=10.0, price=100.0), {})
        assert pf.cash == pytest.approx(9_000.0)

    def test_buy_creates_position(self):
        pf = Portfolio(cash=10_000.0)
        _apply_fill(pf, self._make_buy_fill(qty=10.0, price=100.0), {})
        assert "AAPL" in pf.positions
        assert pf.positions["AAPL"].qty == pytest.approx(10.0)
        assert pf.positions["AAPL"].avg_cost == pytest.approx(100.0)

    def test_second_buy_averages_cost(self):
        pf = Portfolio(cash=50_000.0)
        entry_ts: dict = {}
        _apply_fill(pf, self._make_buy_fill(qty=10.0, price=100.0), entry_ts)
        # Second buy at 120 → avg = (10×100 + 10×120) / 20 = 110
        from backtest.fills import Fill
        fill2 = Fill(
            ts=pd.Timestamp("2024-01-03"),
            symbol="AAPL",
            side="buy",
            qty=10.0,
            fill_price=120.0,
        )
        _apply_fill(pf, fill2, entry_ts)
        assert pf.positions["AAPL"].qty == pytest.approx(20.0)
        assert pf.positions["AAPL"].avg_cost == pytest.approx(110.0)

    def test_sell_increases_cash(self):
        pf = Portfolio(
            cash=0.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        _apply_fill(pf, self._make_sell_fill(qty=10.0, price=150.0), {})
        assert pf.cash == pytest.approx(1_500.0)

    def test_sell_removes_position_when_fully_closed(self):
        pf = Portfolio(
            cash=0.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        _apply_fill(pf, self._make_sell_fill(qty=10.0, price=150.0), {})
        assert "AAPL" not in pf.positions

    def test_sell_preserves_remainder(self):
        pf = Portfolio(
            cash=0.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        _apply_fill(pf, self._make_sell_fill(qty=4.0, price=150.0), {})
        assert pf.positions["AAPL"].qty == pytest.approx(6.0)
        assert pf.positions["AAPL"].avg_cost == pytest.approx(100.0)

    def test_sell_returns_trade_record(self):
        entry_ts = {"AAPL": pd.Timestamp("2024-01-02")}
        pf = Portfolio(
            cash=0.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        trade = _apply_fill(pf, self._make_sell_fill(qty=10.0, price=150.0), entry_ts)
        assert trade is not None
        assert trade["symbol"] == "AAPL"
        assert trade["pnl"] == pytest.approx((150.0 - 100.0) * 10.0)

    def test_buy_returns_none(self):
        pf = Portfolio(cash=10_000.0)
        result = _apply_fill(pf, self._make_buy_fill(), {})
        assert result is None

    def test_sell_unknown_symbol_returns_none(self):
        pf = Portfolio(cash=10_000.0)  # no positions
        result = _apply_fill(pf, self._make_sell_fill(symbol="UNKN"), {})
        assert result is None


# ---------------------------------------------------------------------------
# _bars_at unit tests
# ---------------------------------------------------------------------------

class TestBarsAt:
    def test_returns_bar_for_existing_timestamp(self):
        bars = _make_bars({"AAPL": [100.0, 110.0]})
        ts = bars.index.get_level_values("date").unique()[0]
        result = _bars_at(bars, ts)
        assert "AAPL" in result
        assert result["AAPL"]["close"] == pytest.approx(100.0)

    def test_returns_empty_for_missing_timestamp(self):
        bars = _make_bars({"AAPL": [100.0]})
        fake_ts = pd.Timestamp("1990-01-02")
        assert _bars_at(bars, fake_ts) == {}

    def test_all_symbols_present_at_shared_timestamp(self):
        bars = _make_bars({"AAPL": [100.0, 110.0], "MSFT": [200.0, 210.0]})
        ts = bars.index.get_level_values("date").unique()[0]
        result = _bars_at(bars, ts)
        assert "AAPL" in result
        assert "MSFT" in result
