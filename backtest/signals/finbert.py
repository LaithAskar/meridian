"""
FinBERT sentiment signal wrapper for the Meridian backtester.

Wraps the same FinBERT classifier (ProsusAI/finbert) the live bot uses, so
the backtest measures the live decision boundary exactly.  All non-scoring
logic — news lookup, per-ticker consensus, sell-then-buy order generation —
lives in ``backtest.signals.sentiment_base``.

Threshold default 0.6 matches ``backend/trading/sentiment_engine.py``::
SentimentEngine.finbert_threshold.

Compound score derivation
-------------------------
FinBERT outputs three softmax probabilities (positive / negative / neutral).
Compound = P(positive) - P(negative) ∈ [-1, 1] — same convention as VADER's
compound, so the two backends are drop-in comparable downstream.

Caching
-------
FinBERT inference is expensive (~50-200ms per headline on CPU).  Repeated
backtest runs over the same FNSPID slice would re-classify every headline
from scratch without a cache.

``FinBERTScorer`` keeps an in-memory ``dict[headline_hash, compound]`` and
optionally persists it to a parquet file at
``data/cache/finbert_scores.parquet``.  Hash is sha1 of the stripped,
lowercased headline — FinBERT is deterministic on text input, so a single
global cache (not per-symbol) is correct and de-duplicates headlines that
appear for multiple tickers (common in market-wide news).

Note: this implementation uses a *global* cache file rather than the
per-symbol layout originally sketched in TODO.md 2.3.  Rationale: FinBERT
scores are text-only (no ticker conditioning), so per-symbol files would
re-classify the same headline N times across N tickers.  Global cache is
both simpler and more efficient.  If a per-symbol layout is needed later
(e.g., for sharded distribution), it can be derived from the global cache.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import pandas as pd

from backtest.signals.sentiment_base import NewsProvider, _SentimentStrategy

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE_PATH = _REPO_ROOT / "data" / "cache" / "finbert_scores.parquet"


def _hash_headline(text: str) -> str:
    """Deterministic, collision-resistant hash for caching.

    Strip + lowercase first so trivial whitespace/casing differences hit the
    same cache entry.  sha1 is fast and 40 hex chars is plenty for ~10M
    distinct headlines.
    """
    normalized = (text or "").strip().lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


class FinBERTScorer:
    """FinBERT classifier with disk-backed cache.

    Public API: ``score(text) -> float``, ``save_cache()``.
    Construction is cheap (only loads the cache, not the model).  The model
    is loaded lazily on the first cache-miss score call.
    """

    def __init__(
        self,
        cache_path: Optional[Path] = _DEFAULT_CACHE_PATH,
        device: str = "cpu",
    ) -> None:
        self._cache_path = cache_path
        self._cache: dict[str, float] = {}
        if cache_path is not None and cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                self._cache = dict(zip(df["headline_hash"].astype(str), df["compound"].astype(float)))
            except Exception:
                # Corrupted cache — start fresh rather than crash.
                self._cache = {}
        self._device = device
        self._model = None
        self._tokenizer = None
        self._torch = None

    def _load_model(self) -> None:
        """Lazy model + tokenizer load."""
        from transformers import (  # type: ignore
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )
        import torch  # type: ignore

        self._tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        self._model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
        self._model.eval()
        if self._device != "cpu":
            self._model.to(self._device)
        self._torch = torch

    def _classify(self, text: str) -> float:
        """Run FinBERT on *text*, return compound = P(pos) - P(neg)."""
        if self._model is None:
            self._load_model()
        inputs = self._tokenizer(  # type: ignore[operator]
            text, return_tensors="pt", truncation=True, max_length=512
        )
        if self._device != "cpu":
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with self._torch.no_grad():  # type: ignore[union-attr]
            logits = self._model(**inputs).logits  # type: ignore[misc]
        probs = self._torch.softmax(logits, dim=-1)[0].tolist()  # type: ignore[union-attr]
        id2label = self._model.config.id2label  # type: ignore[union-attr]
        labelled = {id2label[i].lower(): float(probs[i]) for i in range(len(probs))}
        return labelled.get("positive", 0.0) - labelled.get("negative", 0.0)

    def score(self, text: str) -> float:
        if not text:
            return 0.0
        h = _hash_headline(text)
        cached = self._cache.get(h)
        if cached is not None:
            return cached
        compound = self._classify(text)
        self._cache[h] = compound
        return compound

    def save_cache(self) -> None:
        """Persist the in-memory cache to ``self._cache_path``."""
        if self._cache_path is None or not self._cache:
            return
        df = pd.DataFrame(
            {
                "headline_hash": list(self._cache.keys()),
                "compound": list(self._cache.values()),
            }
        )
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(self._cache_path)


class FinBERTStrategy(_SentimentStrategy):
    """FinBERT-driven sentiment strategy.

    Parameters
    ----------
    threshold      : Compound-score threshold; default 0.6 matches the live bot.
    max_positions  : Max concurrent long positions (default 10).
    min_headlines  : Minimum headlines per (ticker, date) for a signal (default 2).
    min_consensus  : Min directional fraction (default 0.6).
    scorer         : Inject a custom scorer (e.g., a stub for tests).  If None,
                     a default ``FinBERTScorer(cache_path=DEFAULT, device='cpu')``
                     is constructed lazily.
    device         : Forwarded to the default scorer (ignored if ``scorer`` is
                     supplied).  Use 'cuda' if a GPU is available.
    cache_path     : Forwarded to the default scorer.  Pass ``None`` to disable
                     disk caching entirely (useful in tests).
    news_provider  : Override the news source (default ``load_news``).
    """

    backend_name = "finbert"

    def __init__(
        self,
        threshold: float = 0.6,
        max_positions: int = 10,
        min_headlines: int = 2,
        min_consensus: float = 0.6,
        scorer: Optional[FinBERTScorer] = None,
        device: str = "cpu",
        cache_path: Optional[Path] = _DEFAULT_CACHE_PATH,
        news_provider: Optional[NewsProvider] = None,
    ) -> None:
        self._scorer = scorer if scorer is not None else FinBERTScorer(
            cache_path=cache_path, device=device
        )
        super().__init__(
            threshold=threshold,
            max_positions=max_positions,
            min_headlines=min_headlines,
            min_consensus=min_consensus,
            news_provider=news_provider,
        )

    def _score(self, text: str) -> float:
        return self._scorer.score(text)

    def save_cache(self) -> None:
        """Persist the FinBERT classification cache to disk."""
        self._scorer.save_cache()
