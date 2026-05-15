"""
Tests for backtest/strategy.py — Order, Position, Portfolio, and Strategy ABC.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from backtest.strategy import Order, Portfolio, Position, Strategy


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

class TestOrder:
    def test_basic_buy_order(self):
        o = Order(symbol="AAPL", side="buy", qty=10.0)
        assert o.symbol == "AAPL"
        assert o.side == "buy"
        assert o.qty == 10.0
        assert o.order_type == "market_next_open"

    def test_basic_sell_order(self):
        o = Order(symbol="MSFT", side="sell", qty=5.0)
        assert o.side == "sell"
        assert o.qty == 5.0

    def test_custom_order_type(self):
        o = Order(symbol="AAPL", side="buy", qty=1.0, order_type="limit")
        assert o.order_type == "limit"

    def test_zero_qty_raises(self):
        with pytest.raises(ValueError, match="qty must be positive"):
            Order(symbol="AAPL", side="buy", qty=0.0)

    def test_negative_qty_raises(self):
        with pytest.raises(ValueError, match="qty must be positive"):
            Order(symbol="AAPL", side="buy", qty=-5.0)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            Order(symbol="AAPL", side="short", qty=1.0)


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class TestPosition:
    def test_market_value_is_qty_times_cost(self):
        p = Position(symbol="AAPL", qty=10.0, avg_cost=150.0)
        assert p.market_value == pytest.approx(1500.0)

    def test_market_value_fractional(self):
        p = Position(symbol="GOOGL", qty=2.5, avg_cost=200.0)
        assert p.market_value == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class TestPortfolio:
    def test_equity_no_positions(self):
        pf = Portfolio(cash=10_000.0)
        assert pf.equity() == pytest.approx(10_000.0)

    def test_equity_with_positions_uses_avg_cost_fallback(self):
        pf = Portfolio(
            cash=5_000.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        # 5000 cash + 10 * 100 = 6000
        assert pf.equity() == pytest.approx(6_000.0)

    def test_equity_marked_to_market(self):
        pf = Portfolio(
            cash=5_000.0,
            positions={"AAPL": Position("AAPL", qty=10.0, avg_cost=100.0)},
        )
        # Mark at 120 → 5000 + 1200 = 6200
        assert pf.equity(prices={"AAPL": 120.0}) == pytest.approx(6_200.0)

    def test_equity_partial_prices_uses_fallback_for_missing(self):
        pf = Portfolio(
            cash=0.0,
            positions={
                "AAPL": Position("AAPL", qty=10.0, avg_cost=100.0),
                "MSFT": Position("MSFT", qty=5.0, avg_cost=200.0),
            },
        )
        # AAPL marked at 150, MSFT uses avg_cost 200
        # 1500 + 1000 = 2500
        assert pf.equity(prices={"AAPL": 150.0}) == pytest.approx(2_500.0)

    def test_num_positions_counts_nonzero(self):
        pf = Portfolio(
            cash=0.0,
            positions={
                "AAPL": Position("AAPL", qty=10.0, avg_cost=100.0),
                "MSFT": Position("MSFT", qty=0.0, avg_cost=200.0),
            },
        )
        assert pf.num_positions == 1

    def test_num_positions_empty(self):
        pf = Portfolio(cash=100.0)
        assert pf.num_positions == 0

    def test_default_positions_is_empty_dict(self):
        pf = Portfolio(cash=1_000.0)
        assert pf.positions == {}


# ---------------------------------------------------------------------------
# Strategy ABC — NoopStrategy subclass
# ---------------------------------------------------------------------------

class NoopStrategy(Strategy):
    """Always returns an empty order list — used to verify the type contract."""

    def on_bar(
        self,
        ts: datetime,
        bars: dict[str, pd.Series],
        portfolio: Portfolio,
    ) -> list[Order]:
        return []


class TestStrategyABC:
    def test_noop_strategy_instantiates(self):
        s = NoopStrategy(max_positions=5)
        assert s.max_positions == 5

    def test_noop_strategy_default_max_positions(self):
        s = NoopStrategy()
        assert s.max_positions == 10

    def test_on_bar_returns_list(self):
        s = NoopStrategy()
        bar = pd.Series({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1_000})
        pf = Portfolio(cash=10_000.0)
        result = s.on_bar(datetime(2024, 1, 2), {"AAPL": bar}, pf)
        assert isinstance(result, list)
        assert result == []

    def test_on_bar_receives_portfolio(self):
        """Verify the portfolio object passed in is the same one the strategy sees."""

        received: list[Portfolio] = []

        class InspectStrategy(Strategy):
            def on_bar(self, ts, bars, portfolio):
                received.append(portfolio)
                return []

        pf = Portfolio(cash=99_000.0)
        s = InspectStrategy()
        s.on_bar(datetime(2024, 1, 2), {}, pf)
        assert received[0] is pf

    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]
