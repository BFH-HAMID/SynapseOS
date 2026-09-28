"""Short-term (session) memory.

Redis-backed when SYNAPSE_REDIS_URL is set; otherwise an in-process TTL cache.
Both expose the same interface: append / history / clear.
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict


class InProcessSessionCache:
    def __init__(self, ttl_s: int = 21600):
        self.ttl = ttl_s
        self._data: dict[str, list[dict]] = defaultdict(list)
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()

    def _alive(self, key: str) -> bool:
        exp = self._expiry.get(key)
        if exp is not None and exp < time.time():
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return False
        return True

    def append(self, key: str, message: dict) -> None:
        with self._lock:
            self._data[key].append(message)
            self._expiry[key] = time.time() + self.ttl

    def history(self, key: str, limit: int = 12) -> list[dict]:
        with self._lock:
            if not self._alive(key):
                return []
            return list(self._data[key][-limit:])

    def clear(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._expiry.pop(key, None)


class RedisSessionCache:
    def __init__(self, url: str, ttl_s: int = 21600):
        import redis  # optional dependency

        self.r = redis.Redis.from_url(url, decode_responses=True)
        self.ttl = ttl_s
        self.r.ping()

    def _key(self, key: str) -> str:
        return f"synapse:sess:{key}"

    def append(self, key: str, message: dict) -> None:
        k = self._key(key)
        self.r.rpush(k, json.dumps(message, default=str))
        self.r.expire(k, self.ttl)

    def history(self, key: str, limit: int = 12) -> list[dict]:
        raw = self.r.lrange(self._key(key), -limit, -1)
        return [json.loads(x) for x in raw]

    def clear(self, key: str) -> None:
        self.r.delete(self._key(key))


def build_session_cache(settings):
    if settings.redis_url:
        try:
            return RedisSessionCache(settings.redis_url, settings.session_ttl_s)
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger("synapseos").warning(
                "Redis unavailable (%s) — using in-process session cache", e)
    return InProcessSessionCache(settings.session_ttl_s)
