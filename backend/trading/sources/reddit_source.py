from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class RedditSource:
    def __init__(self, subreddits: list[str] | None = None, min_score: int = 3):
        self.subreddits = subreddits or ["wallstreetbets", "stocks"]
        self.min_score = min_score
        self._last_fetch = 0.0
        self._cache: list[dict] = []
        self._min_interval = 120

    def fetch_headlines(self) -> list[dict[str, Any]]:
        now = time.time()
        if now - self._last_fetch < self._min_interval and self._cache:
            return self._cache
        all_posts = []
        for sub in self.subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                headers = {"User-Agent": "meridian/1.0"}
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 403:
                    logger.debug(f"Reddit 403 for r/{sub} (cloud IP blocked)")
                    continue
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    score = post.get("score", 0)
                    if score < self.min_score:
                        continue
                    title = post.get("title", "")
                    if title:
                        all_posts.append({
                            "title": title,
                            "source": "reddit",
                            "subreddit": sub,
                            "score": score,
                            "url": f"https://reddit.com{post.get('permalink', '')}",
                            "date": "",
                        })
                time.sleep(1)
            except Exception as e:
                logger.debug(f"Reddit fetch error for r/{sub}: {e}")
        self._cache = all_posts
        self._last_fetch = now
        return all_posts
