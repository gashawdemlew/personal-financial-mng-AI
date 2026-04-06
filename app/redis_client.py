import redis
import os
import sys
import time
import fnmatch
from typing import Dict, Optional

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

from app.config import REDIS_URL


class InMemoryRedisClient:
    def __init__(self):
        self._store: Dict[str, bytes] = {}
        self._expire_at: Dict[str, float] = {}

    def _purge_if_expired(self, key: str):
        exp = self._expire_at.get(key)
        if exp is not None and time.time() >= exp:
            self._store.pop(key, None)
            self._expire_at.pop(key, None)

    def _normalize_key(self, key) -> str:
        return key.decode() if isinstance(key, bytes) else str(key)

    def ping(self):
        return True

    def info(self):
        size_bytes = sum(len(v) for v in self._store.values())
        return {"used_memory_human": f"{size_bytes}B", "mode": "in-memory-fallback"}

    def get(self, key):
        key = self._normalize_key(key)
        self._purge_if_expired(key)
        return self._store.get(key)

    def set(self, key, value):
        key = self._normalize_key(key)
        self._store[key] = value if isinstance(value, bytes) else str(value).encode()
        self._expire_at.pop(key, None)
        return True

    def setex(self, key, ttl_seconds: int, value):
        key = self._normalize_key(key)
        self._store[key] = value if isinstance(value, bytes) else str(value).encode()
        self._expire_at[key] = time.time() + int(ttl_seconds)
        return True

    def incr(self, key):
        key = self._normalize_key(key)
        self._purge_if_expired(key)
        current = self._store.get(key, b"0")
        value = int(current.decode() if isinstance(current, bytes) else str(current)) + 1
        self._store[key] = str(value).encode()
        return value

    def expire(self, key, ttl_seconds: int):
        key = self._normalize_key(key)
        self._purge_if_expired(key)
        if key not in self._store:
            return False
        self._expire_at[key] = time.time() + int(ttl_seconds)
        return True

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            key = self._normalize_key(key)
            self._purge_if_expired(key)
            if key in self._store:
                deleted += 1
                self._store.pop(key, None)
                self._expire_at.pop(key, None)
        return deleted

    def keys(self, pattern: str = "*"):
        matched = []
        for key in list(self._store.keys()):
            self._purge_if_expired(key)
            if key in self._store and fnmatch.fnmatch(key, pattern):
                matched.append(key)
        return matched


def _build_redis_client():
    try:
        client = redis.from_url(REDIS_URL)
        client.ping()
        return client
    except Exception:
        return InMemoryRedisClient()


redis_client = _build_redis_client()
