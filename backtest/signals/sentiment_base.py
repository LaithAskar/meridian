"""
Shared base class for backtest sentiment strategies (VADER + FinBERT).

The two backends differ only in how they score a headline string; everything
else — news lookup per bar, per-ticker consensus, sell-then-buy order
generation, equal-weight sizing — is shared.

Threshold and consensus parameters mirror ``backend/trading/sentiment_engine.py``
so the backtest measures the same decision boundary the live bot uses.

News-timing convention
----------------------
For a daily bar at timestamp ``ts``, the strategy reads news whose timestamp
falls on the same calendar day as ``ts``.  Orders generated on this bar are
filled at ``ts+1``'s open per the engine's fill model, so this is an
EOD-news → next-day-open pattern with no look-ahead.

Empty news for a (symbol, date) is treated as "no signal" (the strategy
neither buys nor sells based on absence of news).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Callable, Literal, Optional

import pandas as pd

from backtest.news_data import load_news
from backtest.strategy import Order, Portfolio, Strategy

# Type alias: a callable matching load_news's signature.  Test fixtures pass
# stub providers so the strategy never touches the parquet cache.
NewsProvider = Callable[[str, "datetime.date", "datetime.date"], pd.DataFrame]

SentimentLabel = Literal["bullish", "bearish", "neutral"]


def _label_for(compound: float, threshold: float) -> SentimentLabel:
    """Map a compound score in [-1, 1] to a discrete bullish/bearish/neutral label.

    Mirrors ``backend/trading/sentiment_engine.py``::SentimentEngine.analyze.
    """
    if compound >= threshold:
        return "bullish"
    if compound <= -threshold:
        return "bearish"
    return "neutral"


def consensus(
    labels: list[SentimentLabel],
    min_count: int,
    min_consensus: float,
) -> SentimentLabel:
    """
    Aggregate a list of per-headline labels into a single per-ticker label.

    Mirrors ``SentimentEngine.get_consensus``:
      - fewer than *min_count* labels  -> neutral (no signal)
      - >= min_consensus fraction bullish (and bullish > bearish) -> bullish
      - >= min_consensus fraction bearish (and bearish > bullish) -> bearish
      - else neutral

    Neutral labels DO count toward the denominator (per the live bot) so
    a flood of neutral headlines suppresses both directions.
    """
    n = len(labels)
    if n < min_count:
        return "neutral"
    bullish = sum(1 for l in labels if l == "bullish")
    bearish = sum(1 for l in labels if l == "bearish")
    if bullish > bearish and bullish / n >= min_consensus:
        return "bullish"
    if bearish > bullish and bearish / n >= min_consensus:
        return "bearish"
    return "neutral"


class _SentimentStrategy(Strategy):
    """
    Base class for headline-driven sentiment strategies.

    Subclasses must implement ``_score(text: str) -> float`` returning a
    compound score in [-1, 1].  All other behaviour lives here.

    Parameters
    ----------
    threshold      : Compound-score magnitude above which a headline is
                     labelled bullish/bearish (default tuned per backend).
    max_positions  : Maximum concurrent long positions.
    min_headlines  : Minimum number of headlines required on a (ticker, date)
                     before any directional label is emitted.  Mirrors the
                     live bot's ``min_count=2`` in get_consensus.
    min_consensus  : Minimum directional fraction for a non-neutral label.
                     0.6 matches the live bot.
    news_provider  : Function (symbol, start, end) -> DataFrame.  Defaults to
                     ``backtest.news_data.load_news``.  Test fixtures override.
    """

    backend_name: str = "sentiment"

    def __init__(
        self,
        threshold: float,
        max_positions: int = 10,
        min_headlines: int = 2,
        min_consensus: float = 0.6,
        news_provider: Optional[NewsProvider] = None,
    ) -> None:
        super().__init__(max_positions=max_positions)
        self._threshold = threshold
        self._min_headlines = min_headlines
        self._min_consensus = min_consensus
        self._news_provider = news_provider if news_provider is not None else load_news

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    def _score(self, text: str) -> float:
        """Return a compound sentiment score in [-1, 1] for *text*."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Strategy ABC implementation
    # ------------------------------------------------------------------

    def on_bar(
        self,
        ts: datetime,
        bars: dict[str, pd.Series],
        portfolio: Portfolio,
    ) -> list[Order]:
        # 1. Per-ticker sentiment: bullish / bearish / neutral
        bar_date = pd.Timestamp(ts).date()
        per_ticker: dict[str, SentimentLabel] = {}
        for sym in bars.keys():
            news = self._news_provider(sym, bar_date, bar_date)
            if news.empty or len(news) < self._min_headlines:
                continue
            labels: list[SentimentLabel] = [
                _label_for(self._score(h), self._threshold)
                for h in news["headline"].astype(str).tolist()
            ]
            label = consensus(labels, self._min_headlines, self._min_consensus)
            if label != "neutral":
                per_ticker[sym] = label

        if not per_ticker:
            return []

        # 2. Order generation: sells first, then buys.
        orders: list[Order] = []
        current_prices = {sym: float(row["close"]) for sym, row in bars.items()}
        equity_now = portfolio.equity(current_prices)
        target_per_slot = (
            equity_now / self.max_positions if self.max_positions > 0 else 0.0
        )
        virtual_cash = portfolio.cash

        # Sells: exit any held position whose ticker is bearish today.
        bearish_held = [
            sym for sym, pos in portfolio.positions.items()
            if per_ticker.get(sym) == "bearish" and pos.qty > 0
        ]
        for sym in bearish_held:
            pos = portfolio.positions[sym]
            orders.append(Order(symbol=sym, side="sell", qty=pos.qty))
            virtual_cash += pos.qty * current_prices.get(sym, pos.avg_cost)

        # Buys: open new positions for bullish tickers not already held.
        n_sells = sum(1 for o in orders if o.side == "sell")
        open_slots = self.max_positions - (portfolio.num_positions - n_sells)

        bullish_unheld = [
            sym for sym, label in per_ticker.items()
            if label == "bullish" and sym not in portfolio.positions
        ]
        # Deterministic ordering — sort by ticker so behaviour is repeatable.
        bullish_unheld.sort()

        for sym in bullish_unheld:
            if open_slots <= 0:
                break
            price = current_prices.get(sym, 0.0)
            if price <= 0.0:
                continue
            qty = math.floor(target_per_slot / price)
            if qty < 1:
                continue
            cost = qty * price
            if virtual_cash < cost:
                continue
            orders.append(Order(symbol=sym, side="buy", qty=float(qty)))
            virtual_cash -= cost
            open_slots -= 1

        return orders
