from __future__ import annotations

import time
import math
from functools import wraps
from typing import Any, Callable, Optional


class TTLCache:
    def __init__(self, ttl: int = 300, maxsize: int = 128):
        self.ttl = ttl
        self.maxsize = maxsize
        self._cache: dict[str, tuple[float, Any]] = {}

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            now = time.time()
            if key in self._cache:
                ts, val = self._cache[key]
                if now - ts < self.ttl:
                    return val
            result = func(*args, **kwargs)
            if len(self._cache) >= self.maxsize:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
            self._cache[key] = (now, result)
            return result
        wrapper.cache_clear = lambda: self._cache.clear()
        return wrapper


class AsyncTTLCache:
    def __init__(self, ttl: int = 300, maxsize: int = 128):
        self.ttl = ttl
        self.maxsize = maxsize
        self._cache: dict[str, tuple[float, Any]] = {}

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            now = time.time()
            if key in self._cache:
                ts, val = self._cache[key]
                if now - ts < self.ttl:
                    return val
            result = await func(*args, **kwargs)
            if len(self._cache) >= self.maxsize:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
            self._cache[key] = (now, result)
            return result
        wrapper.cache_clear = lambda: self._cache.clear()
        return wrapper


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        if b == 0:
            return default
        result = a / b
        if math.isinf(result) or math.isnan(result):
            return default
        return result
    except (ZeroDivisionError, TypeError):
        return default


def format_currency(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "$0.00"
    try:
        v = float(value)
        if abs(v) >= 1e12:
            return f"${v/1e12:.{decimals}f}T"
        if abs(v) >= 1e9:
            return f"${v/1e9:.{decimals}f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.{decimals}f}M"
        return f"${v:,.{decimals}f}"
    except (ValueError, TypeError):
        return "$0.00"


def format_percent(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "0.00%"
    try:
        return f"{float(value):.{decimals}f}%"
    except (ValueError, TypeError):
        return "0.00%"


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))
