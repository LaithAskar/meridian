"""
Tests for backtest/fills.py — Fill dataclass and fill_order function.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from backtest.fills import Fill, SLIPPAGE_BPS, fill_order
from backtest.strategy import Order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILL_TS = datetime(2024, 1, 3)


def make_bar(open_price: float) -> pd.Series:
    """Minimal OHLCV bar with a given open price."""
    return pd.Series({
        "open": open_price,
        "high": open_price * 1.01,
        "low": open_price * 0.99,
        "close": open_price * 1.005,
        "volume": 10_000,
    })


# ---------------------------------------------------------------------------
# fill_order — buy side
# ---------------------------------------------------------------------------

class TestFillOrderBuy:
    def test_known_value_100(self):
        """5 bps on a $100 open → fill at $100.05."""
        order = Order(symbol="AAPL", side="buy", qty=1.0)
        fill = fill_order(order, make_bar(100.0), FILL_TS)
        assert fill is not None
        assert fill.fill_price == pytest.approx(100.05, rel=1e-9)

    def test_known_value_250(self):
        """5 bps on a $250 open → fill at $250.125."""
        order = Order(symbol="MSFT", side="buy", qty=2.0)
        fill = fill_order(order, make_bar(250.0), FILL_TS)
        assert fill.fill_price == pytest.approx(250.0 * (1 + SLIPPAGE_BPS * 1e-4), rel=1e-9)

    def test_buy_pays_more_than_open(self):
        """Slippage is adverse: buyer pays *above* the open."""
        order = Order(symbol="AAPL", side="buy", qty=1.0)
        bar = make_bar(150.0)
        fill = fill_order(order, bar, FILL_TS)
        assert fill.fill_price > 150.0

    def test_fill_fields_buy(self):
        order = Order(symbol="MSFT", side="buy", qty=3.0)
        fill = fill_order(order, make_bar(150.0), FILL_TS)
        assert fill is not None
        assert fill.symbol == "MSFT"
        assert fill.side == "buy"
        assert fill.qty == pytest.approx(3.0)
        assert fill.ts == FILL_TS


# ---------------------------------------------------------------------------
# fill_order — sell side
# ---------------------------------------------------------------------------

class TestFillOrderSell:
    def test_known_value_100(self):
        """5 bps on a $100 open → fill at $99.95."""
        order = Order(symbol="AAPL", side="sell", qty=1.0)
        fill = fill_order(order, make_bar(100.0), FILL_TS)
        assert fill is not None
        assert fill.fill_price == pytest.approx(99.95, rel=1e-9)

    def test_known_value_200(self):
        """5 bps on a $200 open → fill at $199.90."""
        order = Order(symbol="GOOGL", side="sell", qty=5.0)
        fill = fill_order(order, make_bar(200.0), FILL_TS)
        assert fill.fill_price == pytest.approx(200.0 * (1 - SLIPPAGE_BPS * 1e-4), rel=1e-9)

    def test_sell_receives_less_than_open(self):
        """Slippage is adverse: seller receives *below* the open."""
        order = Order(symbol="AAPL", side="sell", qty=1.0)
        fill = fill_order(order, make_bar(150.0), FILL_TS)
        assert fill.fill_price < 150.0

    def test_fill_fields_sell(self):
        order = Order(symbol="TSLA", side="sell", qty=7.0)
        fill = fill_order(order, make_bar(50.0), FILL_TS)
        assert fill is not None
        assert fill.symbol == "TSLA"
        assert fill.side == "sell"
        assert fill.qty == pytest.approx(7.0)
        assert fill.ts == FILL_TS


# ---------------------------------------------------------------------------
# fill_order — cancellation (missing bar)
# ---------------------------------------------------------------------------

class TestFillOrderCancellation:
    def test_none_bar_returns_none(self):
        """Order is cancelled when the next bar is missing (delisted, halted)."""
        order = Order(symbol="DELIST", side="buy", qty=10.0)
        assert fill_order(order, None, FILL_TS) is None

    def test_none_bar_sell_returns_none(self):
        order = Order(symbol="DELIST", side="sell", qty=5.0)
        assert fill_order(order, None, FILL_TS) is None


# ---------------------------------------------------------------------------
# fill_order — gap scenarios
# ---------------------------------------------------------------------------

class TestFillOrderGaps:
    def test_gap_up_buy_uses_open(self):
        """
        A gap-up open is used as-is — no attempt to reconstruct a 'fairer'
        pre-gap price.  The strategy submitted its order at yesterday's close;
        whatever the open is, that's the execution price (plus slippage).
        """
        order = Order(symbol="AAPL", side="buy", qty=1.0)
        gap_bar = pd.Series({
            "open": 200.0,   # gapped significantly above prior close
            "high": 210.0,
            "low": 198.0,
            "close": 205.0,
            "volume": 15_000,
        })
        fill = fill_order(order, gap_bar, FILL_TS)
        assert fill.fill_price == pytest.approx(200.0 * (1 + SLIPPAGE_BPS * 1e-4), rel=1e-9)

    def test_gap_down_sell_uses_open(self):
        """Gap-down open on a sell: seller still gets open − slippage."""
        order = Order(symbol="AAPL", side="sell", qty=1.0)
        gap_bar = pd.Series({
            "open": 80.0,    # gapped down from ~120
            "high": 85.0,
            "low": 78.0,
            "close": 82.0,
            "volume": 20_000,
        })
        fill = fill_order(order, gap_bar, FILL_TS)
        assert fill.fill_price == pytest.approx(80.0 * (1 - SLIPPAGE_BPS * 1e-4), rel=1e-9)


# ---------------------------------------------------------------------------
# Fill dataclass
# ---------------------------------------------------------------------------

class TestFillDataclass:
    def test_fill_is_dataclass(self):
        fill = Fill(
            ts=FILL_TS,
            symbol="AAPL",
            side="buy",
            qty=10.0,
            fill_price=150.075,
        )
        assert fill.ts == FILL_TS
        assert fill.symbol == "AAPL"
        assert fill.side == "buy"
        assert fill.qty == pytest.approx(10.0)
        assert fill.fill_price == pytest.approx(150.075)

    def test_fill_repr_contains_symbol(self):
        fill = Fill(ts=FILL_TS, symbol="MSFT", side="sell", qty=5.0, fill_price=299.85)
        assert "MSFT" in repr(fill)
