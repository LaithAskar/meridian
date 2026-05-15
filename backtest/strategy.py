"""
Strategy interface for the Meridian backtester.

Three data classes model the state passed between the engine and a strategy:

    Order     — an intent to buy or sell (not yet filled)
    Position  — a held position with average cost basis
    Portfolio — full portfolio snapshot (cash + positions + derived equity)

The Strategy ABC defines the single callback the engine calls on every bar.
All three backtest signal sources (quant, VADER, FinBERT) implement this same
interface — only the signal generator injected at construction differs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd


@dataclass
class Order:
    """A request to trade submitted by a strategy on a given bar."""

    symbol: str
    side: Literal["buy", "sell"]
    qty: float                          # number of shares (positive)
    order_type: str = "market_next_open"

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError(f"Order qty must be positive; got {self.qty}")
        if self.side not in ("buy", "sell"):
            raise ValueError(f"Order side must be 'buy' or 'sell'; got {self.side!r}")


@dataclass
class Position:
    """A held position in one symbol."""

    symbol: str
    qty: float          # shares held (positive = long)
    avg_cost: float     # average cost basis per share

    @property
    def market_value(self) -> float:
        """Unrealised market value at avg_cost (placeholder until marked to market)."""
        return self.qty * self.avg_cost


@dataclass
class Portfolio:
    """Full portfolio state at one point in time."""

    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    def equity(self, prices: dict[str, float] | None = None) -> float:
        """
        Total equity = cash + sum of position market values.

        If *prices* is supplied the positions are marked to market;
        otherwise avg_cost is used as a fallback (useful for snapshots
        taken before the engine has a fresh price for every symbol).
        """
        pos_value = 0.0
        for sym, pos in self.positions.items():
            if prices and sym in prices:
                pos_value += pos.qty * prices[sym]
            else:
                pos_value += pos.market_value
        return self.cash + pos_value

    @property
    def num_positions(self) -> int:
        return sum(1 for p in self.positions.values() if p.qty != 0)


class Strategy(ABC):
    """
    Abstract base class for all backtest strategies.

    Subclasses implement ``on_bar``, which the engine calls once per
    timestamp with the current bar data and portfolio state.  The method
    returns a (possibly empty) list of Orders to be filled at the next
    bar's open.

    Parameters
    ----------
    max_positions : int
        Maximum number of concurrent positions the strategy may hold.
        The engine does NOT enforce this limit — it is the strategy's
        responsibility to respect it.
    """

    def __init__(self, max_positions: int = 10) -> None:
        self.max_positions = max_positions

    @abstractmethod
    def on_bar(
        self,
        ts: datetime,
        bars: dict[str, pd.Series],
        portfolio: Portfolio,
    ) -> list[Order]:
        """
        Called once per timestamp.

        Parameters
        ----------
        ts        : current bar timestamp
        bars      : {symbol: Series(open, high, low, close, volume)} for every
                    symbol that has data on this bar
        portfolio : current portfolio state (cash + positions)

        Returns
        -------
        list[Order] — may be empty
        """
        ...
