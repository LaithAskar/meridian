"""
Event-loop engine for the Meridian backtester.

Processing model per trading day t
------------------------------------
    1. Apply pending fills from t-1 at today's open prices (next-bar-open fill).
    2. Mark portfolio to today's close prices.
    3. Snapshot: (equity, cash, num_positions).
    4. Call strategy.on_bar(t, bars_t, portfolio) → new orders.
    5. Queue new orders as pending for t+1.

This strict ordering prevents look-ahead bias: the signal fires on bar t's
data, but the fill uses bar t+1's open.  The strategy never trades at the
price that triggered its signal.

Portfolio accounting
--------------------
  Buy  : cash -= qty × fill_price;  position updated (weighted avg cost basis)
  Sell : cash += qty × fill_price;  position reduced (qty capped at held qty)

Sell qty is always capped at the held qty — the engine does not allow short
positions (DESIGN.md specifies long-only equal-weight positioning).

Cost basis uses weighted average (not FIFO/LIFO).  For single-entry positions
this is identical to FIFO.  For positions built up via multiple buys the avg
cost blends all entries, which is the standard treatment in most backtesting
frameworks and matches the live bot's accounting.

Trade records
-------------
A "closed trade" is recorded each time a sell fill reduces a position.  Each
record captures the entry avg-cost basis at the time of the sell and the fill
price of the sell, making it straightforward for metrics.py to compute hit
rate and win/loss ratios without re-deriving cost basis.

Partial closes produce one trade record per partial-sell event; the
remaining position keeps its original avg cost basis unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from backtest.data import fetch_bars
from backtest.fills import Fill, fill_order
from backtest.strategy import Order, Portfolio, Position, Strategy

_ZERO_QTY_THRESHOLD = 1e-9


@dataclass
class BacktestResult:
    """All outputs produced by Engine.run()."""

    equity_curve: pd.DataFrame
    """DatetimeIndex × (equity, cash, num_positions).  One row per trading day.

    ``equity`` is marked to market at each day's close price.  Use
    ``equity.pct_change().dropna()`` to obtain the daily return series needed
    by metrics.sharpe().
    """

    trades: pd.DataFrame
    """One row per closed (or partially-closed) position.

    Columns
    -------
    symbol        : ticker
    entry_ts      : timestamp when the position was opened (first buy fill)
    exit_ts       : timestamp of the sell fill that closed/reduced the position
    qty           : shares closed in this exit event
    entry_price   : avg cost basis at the time of the sell (per share)
    exit_price    : sell fill price (per share, including slippage)
    pnl           : (exit_price - entry_price) × qty  — realised P&L in dollars
    holding_days  : calendar days between entry_ts and exit_ts
    """


class Engine:
    """
    Drives a Strategy subclass over [start, end], simulating fills and tracking
    portfolio state day by day.

    Parameters
    ----------
    strategy      : concrete Strategy implementation (signal injected here)
    universe      : list of ticker symbols; passed directly to fetch_bars
    start         : inclusive backtest start date
    end           : inclusive backtest end date
    initial_cash  : starting NAV in USD (default 1 000 000)
    max_positions : passed to the strategy; the engine does NOT enforce this
    """

    def __init__(
        self,
        strategy: Strategy,
        universe: list[str],
        start: date,
        end: date,
        initial_cash: float = 1_000_000.0,
        max_positions: int = 10,
    ) -> None:
        self.strategy = strategy
        self.universe = universe
        self.start = start
        self.end = end
        self.initial_cash = initial_cash
        self.max_positions = max_positions

    def run(self) -> BacktestResult:
        """Fetch bars, iterate the event loop, and return a BacktestResult."""
        bars = fetch_bars(self.universe, self.start, self.end)

        if bars.empty:
            return BacktestResult(
                equity_curve=pd.DataFrame(columns=["equity", "cash", "num_positions"]),
                trades=pd.DataFrame(
                    columns=[
                        "symbol", "entry_ts", "exit_ts", "qty",
                        "entry_price", "exit_price", "pnl", "holding_days",
                    ]
                ),
            )

        timestamps = bars.index.get_level_values("date").unique().sort_values()

        portfolio = Portfolio(cash=float(self.initial_cash))
        entry_timestamps: dict[str, datetime] = {}  # symbol → open position ts
        pending: list[Order] = []
        snapshots: list[dict] = []
        closed_trades: list[dict] = []

        for ts in timestamps:
            bars_t = _bars_at(bars, ts)

            # ── Step 1: fill pending orders from the previous bar ────────────
            for order in pending:
                fill = fill_order(order, bars_t.get(order.symbol), ts)
                if fill:
                    trade = _apply_fill(portfolio, fill, entry_timestamps)
                    if trade is not None:
                        closed_trades.append(trade)

            # ── Step 2: mark portfolio to today's close prices ───────────────
            close_prices = {sym: float(row["close"]) for sym, row in bars_t.items()}
            eq = portfolio.equity(prices=close_prices)

            # ── Step 3: snapshot ─────────────────────────────────────────────
            snapshots.append({
                "ts": ts,
                "equity": eq,
                "cash": portfolio.cash,
                "num_positions": portfolio.num_positions,
            })

            # ── Step 4: ask strategy what to do ──────────────────────────────
            pending = list(self.strategy.on_bar(ts, bars_t, portfolio))

        equity_curve = pd.DataFrame(snapshots).set_index("ts")
        equity_curve.index.name = "ts"

        trades_df = (
            pd.DataFrame(closed_trades)
            if closed_trades
            else pd.DataFrame(
                columns=[
                    "symbol", "entry_ts", "exit_ts", "qty",
                    "entry_price", "exit_price", "pnl", "holding_days",
                ]
            )
        )

        return BacktestResult(equity_curve=equity_curve, trades=trades_df)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bars_at(bars: pd.DataFrame, ts: pd.Timestamp) -> dict[str, pd.Series]:
    """
    Return {symbol: OHLCV Series} for a single timestamp from a MultiIndex DataFrame.

    Uses xs (cross-section) on the date level — O(log n) on a sorted index.
    Returns an empty dict if the timestamp is absent.
    """
    try:
        cross = bars.xs(ts, level="date")
    except KeyError:
        return {}
    return {sym: cross.loc[sym] for sym in cross.index}


def _apply_fill(
    portfolio: Portfolio,
    fill: Fill,
    entry_timestamps: dict[str, datetime],
) -> dict | None:
    """
    Apply a confirmed fill to the portfolio in-place.

    Returns a closed-trade record dict when a sell fill reduces a position,
    or None for buy fills (no realised P&L yet).

    Sell qty is silently capped at the held qty to prevent short positions.
    If the symbol is not in the portfolio on a sell, the fill is a no-op.
    """
    if fill.side == "buy":
        portfolio.cash -= fill.qty * fill.fill_price

        if fill.symbol in portfolio.positions:
            pos = portfolio.positions[fill.symbol]
            new_qty = pos.qty + fill.qty
            new_avg = (pos.qty * pos.avg_cost + fill.qty * fill.fill_price) / new_qty
            portfolio.positions[fill.symbol] = Position(fill.symbol, new_qty, new_avg)
        else:
            portfolio.positions[fill.symbol] = Position(
                fill.symbol, fill.qty, fill.fill_price
            )
            entry_timestamps[fill.symbol] = fill.ts

        return None

    # ── sell ────────────────────────────────────────────────────────────────
    if fill.symbol not in portfolio.positions:
        return None

    pos = portfolio.positions[fill.symbol]
    actual_qty = min(fill.qty, pos.qty)
    if actual_qty <= 0:
        return None

    portfolio.cash += actual_qty * fill.fill_price

    entry_ts = entry_timestamps.get(fill.symbol, fill.ts)
    trade = {
        "symbol": fill.symbol,
        "entry_ts": entry_ts,
        "exit_ts": fill.ts,
        "qty": actual_qty,
        "entry_price": pos.avg_cost,
        "exit_price": fill.fill_price,
        "pnl": (fill.fill_price - pos.avg_cost) * actual_qty,
        "holding_days": max(0, (fill.ts - entry_ts).days),
    }

    new_qty = pos.qty - actual_qty
    if new_qty < _ZERO_QTY_THRESHOLD:
        del portfolio.positions[fill.symbol]
        entry_timestamps.pop(fill.symbol, None)
    else:
        portfolio.positions[fill.symbol] = Position(fill.symbol, new_qty, pos.avg_cost)

    return trade
