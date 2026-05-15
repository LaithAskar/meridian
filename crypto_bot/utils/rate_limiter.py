from __future__ import annotations

import time
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

try:
    from filelock import FileLock
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False


class RateLimiter:
    def __init__(self, min_interval: float = 1.5, lock_path: str = "/tmp/meridian_rh.lock"):
        self.min_interval = min_interval
        self._last_call = 0.0
        self._lock = FileLock(lock_path, timeout=5) if FILELOCK_AVAILABLE else None

    def wait(self):
        elapsed = time.time() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.time()

    def __enter__(self):
        if self._lock:
            self._lock.acquire()
        self.wait()
        return self

    def __exit__(self, *args):
        if self._lock:
            self._lock.release()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        r = float(value)
        if math.isnan(r) or math.isinf(r):
            return default
        return r
    except (ValueError, TypeError):
        return default
