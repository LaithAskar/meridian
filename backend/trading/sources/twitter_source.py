from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TwitterSource:
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self.enabled = bool(api_key and api_secret)

    def fetch_headlines(self, query: str = "") -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        logger.info("Twitter source requires paid API key - disabled")
        return []
