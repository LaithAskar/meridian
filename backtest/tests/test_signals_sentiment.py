"""
Tests for backtest/signals/{sentiment_base, vader, finbert}.py.

VADER tests use the real VADER classifier (lightweight rule-based).
FinBERT tests use a stub scorer to avoid loading the real model
(~500 MB download + 5-10 s init).  A separate test exercises
``FinBERTScorer``'s cache behaviour with ``_classify`` monkeypatched.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest

from backtest.signals.finbert import FinBERTScorer, FinBERTStrategy, _hash_headline
from backtest.signals.sentiment_base import _SentimentStrategy, _label_for, consensus
from backtest.signals.vader import VADERStrategy
from backtest.strategy import Order, Portfolio, Position, Strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(sym_prices: dict[str, float]) -> dict[str, pd.Series]:
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


def _news_df(headlines: list[str], on_date: date) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date":      [pd.Timestamp(on_date)] * len(headlines),
            "headline":  headlines,
            "publisher": ["Test"] * len(headlines),
            "url":       ["http://x/"] * len(headlines),
        }
    )


class _NewsStub:
    """Callable news provider for tests: returns per-(symbol, date) headlines."""

    def __init__(self, by_symbol_date: dict[tuple[str, date], list[str]]):
        self._db = by_symbol_date

    def __call__(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        # Tests always call with start == end (single-day lookup)
        headlines = self._db.get((symbol, start), [])
        if not headlines:
            return pd.DataFrame(
                {
                    "date":      pd.Series(dtype="datetime64[ns]"),
                    "headline":  pd.Series(dtype="object"),
                    "publisher": pd.Series(dtype="object"),
                    "url":       pd.Series(dtype="object"),
                }
            )
        return _news_df(headlines, start)


class _DictScorer:
    """FinBERT-shaped stub: returns pre-canned compound scores by text."""

    def __init__(self, mapping: dict[str, float], default: float = 0.0):
        self._mapping = mapping
        self._default = default
        self.call_count = 0

    def score(self, text: str) -> float:
        self.call_count += 1
        return self._mapping.get(text, self._default)

    def save_cache(self) -> None:
        pass


# ---------------------------------------------------------------------------
# sentiment_base helpers
# ---------------------------------------------------------------------------


class TestLabelFor:
    def test_bullish_at_threshold(self):
        assert _label_for(0.6, threshold=0.6) == "bullish"

    def test_bearish_at_negative_threshold(self):
        assert _label_for(-0.6, threshold=0.6) == "bearish"

    def test_neutral_inside_threshold(self):
        assert _label_for(0.3, threshold=0.6) == "neutral"
        assert _label_for(-0.3, threshold=0.6) == "neutral"

    def test_zero_is_neutral(self):
        assert _label_for(0.0, threshold=0.6) == "neutral"


class TestConsensus:
    def test_below_min_count_is_neutral(self):
        assert consensus(["bullish"], min_count=2, min_consensus=0.6) == "neutral"

    def test_majority_bullish_with_min_consensus(self):
        # 4 bullish / 1 neutral = 80% bullish > 60% -> bullish
        labels = ["bullish", "bullish", "bullish", "bullish", "neutral"]
        assert consensus(labels, min_count=2, min_consensus=0.6) == "bullish"

    def test_majority_bearish_with_min_consensus(self):
        labels = ["bearish", "bearish", "bearish", "neutral"]
        assert consensus(labels, min_count=2, min_consensus=0.6) == "bearish"

    def test_split_below_consensus_is_neutral(self):
        # 2 bullish / 2 bearish — neither side has 60% — neutral
        labels = ["bullish", "bullish", "bearish", "bearish"]
        assert consensus(labels, min_count=2, min_consensus=0.6) == "neutral"

    def test_tie_breaks_to_neutral(self):
        labels = ["bullish", "bearish"]
        assert consensus(labels, min_count=2, min_consensus=0.6) == "neutral"

    def test_neutrals_dilute_the_consensus(self):
        # 2 bullish / 5 neutral — bullish/total = 2/7 ≈ 28% — not consensus
        labels = ["bullish", "bullish"] + ["neutral"] * 5
        assert consensus(labels, min_count=2, min_consensus=0.6) == "neutral"


# ---------------------------------------------------------------------------
# _SentimentStrategy via a tiny scorer
# ---------------------------------------------------------------------------


class _ConstScorer(_SentimentStrategy):
    """Strategy returning a fixed compound score for every headline."""

    backend_name = "const"

    def __init__(self, score_value: float, **kwargs):
        super().__init__(**kwargs)
        self._sv = score_value

    def _score(self, text: str) -> float:
        return self._sv


class TestSentimentBaseOrderGeneration:
    def setup_method(self):
        # AAPL has 3 strongly-bullish-tagged headlines on the test date
        self.test_date = date(2020, 6, 5)
        self.news = _NewsStub({
            ("AAPL", self.test_date): ["h1", "h2", "h3"],   # bullish-strong
            ("MSFT", self.test_date): ["m1"],               # below min_headlines
        })

    def test_bullish_consensus_emits_buy(self):
        # Score 0.8 with threshold 0.6 -> bullish.  3 bullish / 3 total = 1.0 >= 0.6
        strat = _ConstScorer(
            score_value=0.8,
            threshold=0.6,
            max_positions=2,
            min_headlines=2,
            min_consensus=0.6,
            news_provider=self.news,
        )
        bars = _bar({"AAPL": 100.0, "MSFT": 200.0})
        portfolio = Portfolio(cash=10_000.0)
        orders = strat.on_bar(datetime(2020, 6, 5), bars, portfolio)

        assert len(orders) == 1
        assert orders[0].symbol == "AAPL"
        assert orders[0].side == "buy"
        # equity_now=10_000, max_positions=2, target_per_slot=5000, qty=50 @ $100
        assert orders[0].qty == 50.0

    def test_bearish_consensus_emits_sell_only_if_held(self):
        # Score -0.8 -> bearish for all symbols today
        strat = _ConstScorer(
            score_value=-0.8,
            threshold=0.6,
            min_headlines=2,
            min_consensus=0.6,
            news_provider=self.news,
        )
        bars = _bar({"AAPL": 100.0})
        # AAPL is held; bearish today -> should be sold
        portfolio = Portfolio(
            cash=1_000.0,
            positions={"AAPL": Position(symbol="AAPL", qty=10.0, avg_cost=90.0)},
        )
        orders = strat.on_bar(datetime(2020, 6, 5), bars, portfolio)
        assert len(orders) == 1
        assert orders[0].symbol == "AAPL"
        assert orders[0].side == "sell"
        assert orders[0].qty == 10.0

    def test_no_news_emits_no_orders(self):
        empty_news = _NewsStub({})
        strat = _ConstScorer(score_value=0.9, threshold=0.6, news_provider=empty_news)
        bars = _bar({"AAPL": 100.0})
        orders = strat.on_bar(datetime(2020, 6, 5), bars, Portfolio(cash=10_000.0))
        assert orders == []

    def test_below_min_headlines_emits_no_orders(self):
        # Only 1 headline for AAPL; min_headlines=2 -> neutral
        few_news = _NewsStub({("AAPL", self.test_date): ["only one"]})
        strat = _ConstScorer(
            score_value=0.9,
            threshold=0.6,
            min_headlines=2,
            news_provider=few_news,
        )
        bars = _bar({"AAPL": 100.0})
        orders = strat.on_bar(datetime(2020, 6, 5), bars, Portfolio(cash=10_000.0))
        assert orders == []

    def test_max_positions_limit_respected(self):
        # 3 bullish tickers, max_positions=1, no current holdings -> 1 buy
        news = _NewsStub({
            ("AAPL", self.test_date): ["a", "b"],
            ("MSFT", self.test_date): ["c", "d"],
            ("GOOGL", self.test_date): ["e", "f"],
        })
        strat = _ConstScorer(
            score_value=0.9,
            threshold=0.6,
            max_positions=1,
            min_headlines=2,
            news_provider=news,
        )
        bars = _bar({"AAPL": 100.0, "MSFT": 200.0, "GOOGL": 300.0})
        orders = strat.on_bar(datetime(2020, 6, 5), bars, Portfolio(cash=10_000.0))
        assert len(orders) == 1
        # Deterministic ordering: alphabetical
        assert orders[0].symbol == "AAPL"

    def test_already_held_bullish_not_double_bought(self):
        news = _NewsStub({("AAPL", self.test_date): ["a", "b", "c"]})
        strat = _ConstScorer(score_value=0.9, threshold=0.6, news_provider=news)
        bars = _bar({"AAPL": 100.0})
        portfolio = Portfolio(
            cash=10_000.0,
            positions={"AAPL": Position(symbol="AAPL", qty=5.0, avg_cost=100.0)},
        )
        orders = strat.on_bar(datetime(2020, 6, 5), bars, portfolio)
        # No buy (already held) and no sell (it's bullish, not bearish)
        assert orders == []


# ---------------------------------------------------------------------------
# VADERStrategy (uses real VADER — light, deterministic, no network)
# ---------------------------------------------------------------------------


class TestVADERStrategy:
    def test_is_strategy_subclass(self):
        assert issubclass(VADERStrategy, Strategy)

    def test_score_is_in_unit_interval(self):
        strat = VADERStrategy(news_provider=_NewsStub({}))
        # VADER compound is in [-1, 1]
        assert -1.0 <= strat._score("excellent quarter, record beat") <= 1.0
        assert -1.0 <= strat._score("collapse, bankruptcy filing") <= 1.0
        assert strat._score("") == 0.0

    def test_strongly_positive_headline_yields_buy(self):
        # Two unambiguously positive headlines -> compound clearly above 0.35
        news = _NewsStub({
            ("AAPL", date(2020, 6, 5)): [
                "Excellent earnings beat estimates by record margin, fantastic results",
                "Outstanding revenue growth, profit surges, stellar performance",
            ],
        })
        strat = VADERStrategy(
            threshold=0.35, max_positions=1, min_headlines=2, min_consensus=0.6,
            news_provider=news,
        )
        orders = strat.on_bar(datetime(2020, 6, 5), _bar({"AAPL": 100.0}), Portfolio(cash=10_000.0))
        assert len(orders) == 1
        assert orders[0].symbol == "AAPL"
        assert orders[0].side == "buy"


# ---------------------------------------------------------------------------
# FinBERTScorer caching (no model load — _classify is monkeypatched)
# ---------------------------------------------------------------------------


class TestFinBERTScorerCaching:
    def test_cache_hit_skips_classification(self, monkeypatch, tmp_path):
        scorer = FinBERTScorer(cache_path=tmp_path / "fb.parquet")

        calls = []
        def fake_classify(self, text):
            calls.append(text)
            return 0.42 if "good" in text else -0.42

        monkeypatch.setattr(FinBERTScorer, "_classify", fake_classify)

        # First call: miss
        assert scorer.score("very good news") == 0.42
        # Second call (identical text): cache hit, no _classify call
        assert scorer.score("very good news") == 0.42
        assert len(calls) == 1

        # Different text: miss
        assert scorer.score("terrible bad outcome") == -0.42
        assert len(calls) == 2

    def test_empty_text_returns_zero_without_classifying(self, monkeypatch):
        scorer = FinBERTScorer(cache_path=None)

        def fake_classify(self, text):
            pytest.fail("classify must not be called on empty text")

        monkeypatch.setattr(FinBERTScorer, "_classify", fake_classify)
        assert scorer.score("") == 0.0

    def test_save_and_reload_cache(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "fb.parquet"

        monkeypatch.setattr(
            FinBERTScorer, "_classify",
            lambda self, text: 0.7 if "good" in text else -0.7,
        )

        scorer1 = FinBERTScorer(cache_path=cache_path)
        _ = scorer1.score("good thing happened")
        _ = scorer1.score("bad thing happened")
        scorer1.save_cache()
        assert cache_path.exists()

        # Reload — no _classify calls allowed for already-scored texts
        calls = []
        def fake_classify(self, text):
            calls.append(text)
            return 999.9  # would be obviously wrong if cache miss

        monkeypatch.setattr(FinBERTScorer, "_classify", fake_classify)
        scorer2 = FinBERTScorer(cache_path=cache_path)
        assert scorer2.score("good thing happened") == 0.7
        assert scorer2.score("bad thing happened") == -0.7
        assert calls == []  # both came from disk cache

    def test_corrupt_cache_starts_fresh(self, tmp_path):
        cache_path = tmp_path / "fb.parquet"
        cache_path.write_text("not a parquet file")  # corrupt
        # Should not raise
        scorer = FinBERTScorer(cache_path=cache_path)
        assert scorer._cache == {}

    def test_hash_is_normalized(self):
        # Whitespace and case differences hash to the same key
        assert _hash_headline("  Hello WORLD ") == _hash_headline("hello world")
        # But content differences don't
        assert _hash_headline("hello") != _hash_headline("hello!")

    def test_cache_path_none_disables_persistence(self, monkeypatch, tmp_path):
        scorer = FinBERTScorer(cache_path=None)
        monkeypatch.setattr(FinBERTScorer, "_classify", lambda self, text: 0.5)
        scorer.score("anything")
        scorer.save_cache()
        # No file should have been created anywhere reasonable
        assert not (tmp_path / "fb.parquet").exists()


# ---------------------------------------------------------------------------
# FinBERTStrategy with injected stub scorer
# ---------------------------------------------------------------------------


class TestFinBERTStrategy:
    def test_is_strategy_subclass(self):
        assert issubclass(FinBERTStrategy, Strategy)

    def test_uses_injected_scorer(self):
        scorer = _DictScorer(
            mapping={
                "h1": 0.8,   # bullish
                "h2": 0.8,
                "h3": 0.8,
            },
            default=0.0,
        )
        news = _NewsStub({("AAPL", date(2020, 6, 5)): ["h1", "h2", "h3"]})
        strat = FinBERTStrategy(
            scorer=scorer,
            threshold=0.6,
            max_positions=1,
            min_headlines=2,
            news_provider=news,
        )
        orders = strat.on_bar(datetime(2020, 6, 5), _bar({"AAPL": 100.0}), Portfolio(cash=10_000.0))
        assert len(orders) == 1
        assert orders[0].side == "buy"
        assert scorer.call_count == 3

    def test_save_cache_passthrough(self, tmp_path):
        scorer = _DictScorer(mapping={}, default=0.0)
        # Mark whether save_cache was called
        called = {"yes": False}
        scorer.save_cache = lambda: called.__setitem__("yes", True)  # type: ignore[assignment]
        strat = FinBERTStrategy(scorer=scorer, news_provider=_NewsStub({}))
        strat.save_cache()
        assert called["yes"] is True
