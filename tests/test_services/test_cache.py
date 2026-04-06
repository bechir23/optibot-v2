"""Tests for 3-tier cache."""
import asyncio
import time
from unittest.mock import AsyncMock

from app.services.cache import TieredCache, _L1Cache


class TestL1Cache:
    def test_set_and_get(self):
        c = _L1Cache()
        c.set("key", "value")
        assert c.get("key") == "value"

    def test_ttl_expiry(self):
        c = _L1Cache()
        c.set("key", "value", ttl=0.05)
        assert c.get("key") == "value"
        # Avoid flaky timing on busy CI/host clocks by polling for expiry.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if c.get("key") is None:
                break
            time.sleep(0.01)
        assert c.get("key") is None

    def test_lru_eviction(self):
        c = _L1Cache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_clear(self):
        c = _L1Cache()
        c.set("a", 1)
        c.clear()
        assert c.get("a") is None


class TestTieredCache:
    def test_l1_hit(self):
        redis_mock = AsyncMock()
        cache = TieredCache(redis_mock)
        asyncio.run(cache.set("key", {"data": 42}, l1_ttl=60, l2_ttl=3600))
        result = asyncio.run(cache.get("key"))
        assert result == {"data": 42}

    def test_l2_hit_promotes_to_l1(self):
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value='{"data": 42}')
        cache = TieredCache(redis_mock)
        result = asyncio.run(cache.get("key"))
        assert result == {"data": 42}
        # Now in L1 — Redis not needed
        redis_mock.get = AsyncMock(return_value=None)
        result2 = asyncio.run(cache.get("key"))
        assert result2 == {"data": 42}

    def test_miss(self):
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        cache = TieredCache(redis_mock)
        result = asyncio.run(cache.get("nonexistent"))
        assert result is None

    def test_delete_clears_both_tiers(self):
        redis_mock = AsyncMock()
        cache = TieredCache(redis_mock)
        asyncio.run(cache.set("key", "value"))
        asyncio.run(cache.delete("key"))
        redis_mock.get = AsyncMock(return_value=None)
        assert asyncio.run(cache.get("key")) is None
