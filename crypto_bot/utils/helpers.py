from __future__ import annotations

import math
from typing import Any


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


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
