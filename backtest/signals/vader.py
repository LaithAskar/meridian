"""
VADER sentiment signal wrapper for the Meridian backtester.

Wraps the same VADER classifier (``vaderSentiment.SentimentIntensityAnalyzer``)
the live bot uses, so the backtest measures the live decision boundary
exactly.  All non-scoring logic — news lookup, per-ticker consensus,
sell-then-buy order generation — lives in ``backtest.signals.sentiment_base``.

Threshold default 0.35 matches ``backend/trading/sentiment_engine.py``::
SentimentEngine.vader_threshold.
"""

from __future__ import annotations

from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from backtest.signals.sentiment_base import NewsProvider, _SentimentStrategy


class VADERStrategy(_SentimentStrategy):
    """VADER-driven sentiment strategy.

    Parameters
    ----------
    threshold      : Compound-score threshold; default 0.35 matches the live bot.
    max_positions  : Max concurrent long positions (default 10).
    min_headlines  : Minimum headlines per (ticker, date) for a signal (default 2).
    min_consensus  : Min directional fraction (default 0.6).
    news_provider  : Override the news source (default ``load_news``).
    """

    backend_name = "vader"

    def __init__(
        self,
        threshold: float = 0.35,
        max_positions: int = 10,
        min_headlines: int = 2,
        min_consensus: float = 0.6,
        news_provider: Optional[NewsProvider] = None,
    ) -> None:
        # VADER is lightweight (rule-based, no model download); construct
        # once per instance.
        self._vader = SentimentIntensityAnalyzer()
        super().__init__(
            threshold=threshold,
            max_positions=max_positions,
            min_headlines=min_headlines,
            min_consensus=min_consensus,
            news_provider=news_provider,
        )

    def _score(self, text: str) -> float:
        if not text:
            return 0.0
        return float(self._vader.polarity_scores(text)["compound"])
