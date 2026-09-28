"""In-memory token-bucket rate limiter (per API key / client IP)."""
from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    def __init__(self, capacity: int, refill_per_s: float):
        self.capacity = capacity
        self.refill = refill_per_s
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, (1.0 - tokens) / max(self.refill, 1e-9)
