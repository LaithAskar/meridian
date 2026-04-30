from __future__ import annotations

import logging
from typing import Any, Optional
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

_analyzer = SentimentIntensityAnalyzer()


class SentimentEngine:
    def __init__(self, vader_threshold: float = 0.35):
        self.vader_threshold = vader_threshold
        self._cache: dict[str, dict] = {}

    def analyze(self, text: str, ticker: Optional[str] = None) -> dict[str, Any]:
        if not text:
            return {"compound": 0.0, "label": "neutral", "passed": False}
        try:
            scores = _analyzer.polarity_scores(text)
            compound = scores["compound"]
            passed = abs(compound) >= self.vader_threshold
            if compound >= self.vader_threshold:
                label = "bullish"
            elif compound <= -self.vader_threshold:
                label = "bearish"
            else:
                label = "neutral"
            return {
                "compound": round(compound, 4),
                "pos": round(scores["pos"], 4),
                "neg": round(scores["neg"], 4),
                "neu": round(scores["neu"], 4),
                "label": label,
                "passed": passed,
                "ticker": ticker,
            }
        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            return {"compound": 0.0, "label": "neutral", "passed": False}

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
