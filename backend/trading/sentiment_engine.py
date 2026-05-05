from __future__ import annotations

import logging
from typing import Any, Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

_vader = SentimentIntensityAnalyzer()


class _FinBERTBackend:
    """FinBERT (ProsusAI/finbert) classifier. Three labels: positive,
    negative, neutral. Compound score derived as (P_pos - P_neg) ∈ [-1, 1]
    so it's drop-in comparable to VADER's compound."""

    def __init__(self, device: str = "cpu"):
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch

        self._torch = torch
        logger.info("Loading FinBERT (ProsusAI/finbert) ...")
        self._tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        self._model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
        self._model.eval()
        if device != "cpu":
            self._model.to(device)
        self._device = device
        # id2label per HF model card: {0:'positive', 1:'negative', 2:'neutral'}
        self._id2label = self._model.config.id2label
        logger.info(f"FinBERT loaded on {device}, labels={self._id2label}")

    def score(self, text: str) -> dict[str, float]:
        inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        if self._device != "cpu":
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with self._torch.no_grad():
            logits = self._model(**inputs).logits
        probs = self._torch.softmax(logits, dim=-1)[0].tolist()
        result = {self._id2label[i].lower(): float(probs[i]) for i in range(len(probs))}
        result["compound"] = result.get("positive", 0.0) - result.get("negative", 0.0)
        return result


class SentimentEngine:
    """Sentiment classifier with FinBERT (preferred for financial text) and
    VADER fallback. Returns a unified dict regardless of backend so callers
    don't need to change.

    Compound score is in [-1, 1] for both backends:
    - VADER: standard compound
    - FinBERT: P(positive) - P(negative)
    """

    def __init__(
        self,
        vader_threshold: float = 0.35,
        finbert_threshold: float = 0.6,
        finbert_device: str = "cpu",
        prefer_finbert: bool = True,
    ):
        self.vader_threshold = vader_threshold
        self.finbert_threshold = finbert_threshold
        self._finbert: Optional[_FinBERTBackend] = None
        self.backend = "vader"
        self.threshold = vader_threshold

        if prefer_finbert:
            try:
                self._finbert = _FinBERTBackend(device=finbert_device)
                self.backend = "finbert"
                self.threshold = finbert_threshold
                logger.info(f"SentimentEngine using FinBERT (threshold={finbert_threshold})")
            except Exception as e:
                logger.warning(f"FinBERT load failed, falling back to VADER: {e}")
                self.backend = "vader"
                self.threshold = vader_threshold
        else:
            logger.info(f"SentimentEngine using VADER (threshold={vader_threshold})")

        self._cache: dict[str, dict] = {}

    def analyze(self, text: str, ticker: Optional[str] = None) -> dict[str, Any]:
        if not text:
            return {"compound": 0.0, "label": "neutral", "passed": False, "backend": self.backend}
        try:
            if self.backend == "finbert" and self._finbert is not None:
                scores = self._finbert.score(text)
                compound = scores["compound"]
                pos = scores.get("positive", 0.0)
                neg = scores.get("negative", 0.0)
                neu = scores.get("neutral", 0.0)
            else:
                vscores = _vader.polarity_scores(text)
                compound = vscores["compound"]
                pos = vscores["pos"]
                neg = vscores["neg"]
                neu = vscores["neu"]

            passed = abs(compound) >= self.threshold
            if compound >= self.threshold:
                label = "bullish"
            elif compound <= -self.threshold:
                label = "bearish"
            else:
                label = "neutral"
            return {
                "compound": round(compound, 4),
                "pos": round(pos, 4),
                "neg": round(neg, 4),
                "neu": round(neu, 4),
                "label": label,
                "passed": passed,
                "ticker": ticker,
                "backend": self.backend,
            }
        except Exception as e:
            logger.error(f"Sentiment analysis error ({self.backend}): {e}")
            return {"compound": 0.0, "label": "neutral", "passed": False, "backend": self.backend}

    def analyze_batch(self, items: list[dict]) -> list[dict]:
        results = []
        for item in items:
            text = item.get("title", "") or item.get("text", "")
            ticker = item.get("ticker")
            result = self.analyze(text, ticker)
            result["source_item"] = item
            results.append(result)
        return results

    def get_consensus(self, sentiments: list[dict], min_count: int = 2) -> dict[str, Any]:
        if len(sentiments) < min_count:
            return {"direction": "neutral", "strength": 0, "count": len(sentiments), "consensus": False}
        bullish = sum(1 for s in sentiments if s.get("label") == "bullish")
        bearish = sum(1 for s in sentiments if s.get("label") == "bearish")
        total = len(sentiments)
        if bullish > bearish and bullish / total >= 0.6:
            return {"direction": "bullish", "strength": bullish / total, "count": total, "consensus": True}
        elif bearish > bullish and bearish / total >= 0.6:
            return {"direction": "bearish", "strength": bearish / total, "count": total, "consensus": True}
        return {"direction": "neutral", "strength": 0, "count": total, "consensus": False}
