"""
Fill model for the Meridian backtester.

Every order is treated as a market order filled at the *next* bar's open
price with 5 bps slippage applied adversely on each side.  This is the
standard quant-backtest convention for daily-bar strategies and models two
real-world frictions simultaneously:

  1. Execution latency — you cannot fill at the close price that triggered
     the signal; you get the next morning's open.
  2. Adverse selection — market impact and spread mean buyers pay a little
     more than the mid and sellers receive a little less.

Design decisions recorded here so they survive code review:

* No partial-fill model.  The universe is the Jan-2010 S&P 100: 100 of the
  most liquid US large-caps.  At the equal-weight position sizes used in this
  backtest (~1% NAV per position), assuming full fills at the open is
  realistic.  Partial-fill modelling requires intraday volume data we don't
  have (yfinance daily only).

* Gap-up / gap-down handling: the open price is used as-is.  A gap is already
  captured in the slippage model because the *previous* close is where the
  signal fired; whatever the open is — even a violent gap — is our fill.
  Attempting to interpolate a "fair" fill inside the gap would be speculation.

* Delisted / missing bar: ``fill_order`` returns ``None``.  The engine
  records a cancellation; the strategy is not charged any cost.  This matches
  real-world behaviour: if you can't buy a delisted stock, the order silently
  expires.

SLIPPAGE_BPS is a module-level constant so it can be overridden in tests or
future sensitivity analyses without monkey-patching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from backtest.strategy import Order

SLIPPAGE_BPS: float = 5.0  # one-way cost in basis points (5 bps = 0.05 %)


@dataclass
class Fill:
    """A confirmed execution record for one Order."""

    ts: datetime                  # timestamp of the fill bar (next bar's ts)
    symbol: str
    side: Literal["buy", "sell"]
    qty: float                    # shares filled (always positive)
    fill_price: float             # per-share price including slippage


def fill_order(
    order: Order,
    next_bar: pd.Series | None,
    ts: datetime,
) -> Fill | None:
    """
    Simulate a market fill at *next_bar*'s open with ``SLIPPAGE_BPS`` slippage.

    Parameters
    ----------
    order    : Order submitted by the strategy on the current bar.
    next_bar : OHLCV Series for the bar at which execution occurs (the bar
               immediately following the signal bar).  Pass ``None`` when
               the symbol has no data for that timestamp — the order is
               then cancelled and ``None`` is returned.
    ts       : Timestamp of *next_bar* (becomes ``Fill.ts``).

    Returns
    -------
    Fill if the order can be executed, ``None`` if it must be cancelled.
    """
    if next_bar is None:
        return None

    open_price = float(next_bar["open"])
    slip = SLIPPAGE_BPS * 1e-4  # convert bps → fraction

    fill_price = open_price * (1.0 + slip) if order.side == "buy" else open_price * (1.0 - slip)

    return Fill(
        ts=ts,
        symbol=order.symbol,
        side=order.side,
        qty=order.qty,
        fill_price=fill_price,
    )
