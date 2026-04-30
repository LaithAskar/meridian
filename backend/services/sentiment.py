from __future__ import annotations

import logging
from typing import Any
from datetime import datetime

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from backend.utils.helpers import TTLCache, safe_float

logger = logging.getLogger(__name__)

_analyzer = SentimentIntensityAnalyzer()


def analyze_text(text: str) -> dict[str, float]:
    if not text:
        return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}
    try:
        scores = _analyzer.polarity_scores(text)
        return {
            "compound": round(scores["compound"], 4),
            "pos": round(scores["pos"], 4),
            "neg": round(scores["neg"], 4),
            "neu": round(scores["neu"], 4),
        }
    except Exception:
        return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}


def classify_sentiment(compound: float) -> str:
    if compound >= 0.05:
        return "Bullish"
    elif compound <= -0.05:
        return "Bearish"
    return "Neutral"


@TTLCache(ttl=300, maxsize=100)
def get_news_sentiment(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        news_items = t.news or []

        articles = []
        total_compound = 0.0
        count = 0

        for item in news_items[:20]:
            try:
                # yfinance >= 1.2.0 uses nested content format
                content = item.get("content", item)
                title = content.get("title", "") if isinstance(content, dict) else item.get("title", "")
                summary = ""
                pub_date = ""
                source = ""

                if isinstance(content, dict):
                    summary = content.get("summary", "")
                    pub_date = content.get("pubDate", "") or content.get("publishedAt", "")
                    provider = content.get("provider", {})
                    if isinstance(provider, dict):
                        source = provider.get("displayName", "")
                    elif isinstance(provider, str):
                        source = provider
                else:
                    summary = item.get("summary", "")
                    pub_date = item.get("providerPublishTime", "")
                    source = item.get("publisher", "")

                if not title:
                    continue

                text_for_analysis = f"{title}. {summary}" if summary else title
                sentiment = analyze_text(text_for_analysis)
                compound = sentiment["compound"]
                total_compound += compound
                count += 1

                # Format date
                date_str = ""
                if pub_date:
                    try:
                        if isinstance(pub_date, (int, float)):
                            date_str = datetime.fromtimestamp(pub_date).isoformat()
                        else:
                            date_str = str(pub_date)
                    except Exception:
                        date_str = str(pub_date)

                link = ""
                if isinstance(content, dict):
                    link = content.get("canonicalUrl", {}).get("url", "") if isinstance(content.get("canonicalUrl"), dict) else ""
                if not link:
                    link = item.get("link", "") or item.get("url", "")

                articles.append({
                    "title": title,
                    "summary": summary[:200] if summary else "",
                    "source": source,
                    "date": date_str,
                    "url": link,
                    "sentiment": classify_sentiment(compound),
                    "compound": round(compound, 4),
                    "score": round(compound, 4),
                })
            except Exception as e:
                logger.debug(f"Error parsing news item: {e}")
                continue

        avg_compound = total_compound / count if count > 0 else 0.0
        aggregate = classify_sentiment(avg_compound)

        bullish = sum(1 for a in articles if a["sentiment"] == "Bullish")
        bearish = sum(1 for a in articles if a["sentiment"] == "Bearish")
        neutral = sum(1 for a in articles if a["sentiment"] == "Neutral")

        return {
            "ticker": ticker.upper(),
            "articles": articles,
            "aggregate": aggregate,
            "aggregateSentiment": {
                "score": round(avg_compound, 4),
                "label": "positive" if aggregate == "Bullish" else "negative" if aggregate == "Bearish" else "neutral",
            },
            "stats": {
                "total": count,
                "bullish": bullish,
                "bearish": bearish,
                "neutral": neutral,
                "averageCompound": round(avg_compound, 4),
            },
        }
    except Exception as e:
        logger.error(f"News sentiment error for {ticker}: {e}")
        return {
            "ticker": ticker.upper(),
            "articles": [],
            "aggregate": "Neutral",
            "aggregateSentiment": {"score": 0, "label": "neutral"},
            "stats": {"total": 0, "bullish": 0, "bearish": 0, "neutral": 0, "averageCompound": 0},
        }
