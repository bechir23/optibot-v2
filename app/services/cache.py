"""Three-tier cache — Microsoft + OptiBot pattern.

L1: In-memory LRU with TTL (<1ms) — hot data
L2: Redis with TTL (<5ms) — warm data
L3: Supabase (50-200ms) — cold data

Cache operations never crash the call. If all tiers fail, the function
proceeds without cached data (graceful degradation).
"""
from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from typing import Any

from app.observability.metrics import record_cache_hit, record_cache_miss
from app.services.redis_client import RedisClient

logger = logging.getLogger(__name__)


class _L1Cache:
    """In-memory LRU cache with TTL. Thread-safe via GIL for single-threaded async."""

    def __init__(self, max_size: int = 500):
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at > 0 and time.monotonic() > expires_at:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: float = 0) -> None:
        expires_at = time.monotonic() + ttl if ttl > 0 else 0
        self._data[key] = (value, expires_at)
        self._data.move_to_end(key)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


class TieredCache:
    """Three-tier cache: L1 memory → L2 Redis → L3 Supabase.

    Usage:
        cache = TieredCache(redis_client)
        value = await cache.get("mutuelle:MGEN:ivr_map")
        if value is None:
            value = await fetch_from_db()
            await cache.set("mutuelle:MGEN:ivr_map", value, l1_ttl=300, l2_ttl=3600)
    """

    def __init__(self, redis: RedisClient, l1_max_size: int = 500):
        self._l1 = _L1Cache(max_size=l1_max_size)
        self._redis = redis

    async def get(self, key: str) -> Any | None:
        """Try L1, then L2 (Redis). Returns None if not found in either."""
        # L1: in-memory
        value = self._l1.get(key)
        if value is not None:
            logger.debug("Cache L1 hit: %s", key)
            record_cache_hit("l1")
            return value

        # L2: Redis
        raw = await self._redis.get(f"cache:{key}")
        if raw is not None:
            try:
                value = json.loads(raw)
                self._l1.set(key, value, ttl=60)  # Promote to L1 for 60s
                logger.debug("Cache L2 hit: %s", key)
                record_cache_hit("l2")
                return value
            except (json.JSONDecodeError, TypeError):
                pass

        logger.debug("Cache miss: %s", key)
        record_cache_miss("l1_l2")
        return None

    async def set(self, key: str, value: Any, l1_ttl: float = 60, l2_ttl: int = 3600) -> None:
        """Set value in L1 and L2."""
        self._l1.set(key, value, ttl=l1_ttl)
        try:
            serialized = json.dumps(value, default=str)
            await self._redis.setex(f"cache:{key}", l2_ttl, serialized)
        except Exception as e:
            logger.warning("Cache L2 set failed for key=%s: %s", key, e)

    async def delete(self, key: str) -> None:
        """Invalidate across all tiers."""
        self._l1.delete(key)
        await self._redis.delete(f"cache:{key}")

    def clear_l1(self) -> None:
        """Clear in-memory cache. Useful for testing or config refresh."""
        self._l1.clear()
