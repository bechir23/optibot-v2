"""Async Redis client with circuit breaker and graceful fallback.

Pattern: same circuit breaker as OptiBot v1 supabase.py but async-native.
If Redis is down, cache operations are silently skipped — never crash the call.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisClient:
    """Production Redis client with connection pooling and circuit breaker."""

    def __init__(self, url: str = "redis://localhost:6379/0", max_connections: int = 20):
        self._url = url
        self._pool: aioredis.ConnectionPool | None = None
        self._client: aioredis.Redis | None = None
        self._max_connections = max_connections

        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0
        self._failure_threshold = 5
        self._recovery_timeout = 60.0  # seconds
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Initialize connection pool."""
        self._pool = aioredis.ConnectionPool.from_url(
            self._url, max_connections=self._max_connections, decode_responses=True
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        logger.info("Redis connected: %s", self._url)

    async def close(self) -> None:
        """Gracefully close connections."""
        if self._client:
            await self._client.aclose()
        if self._pool:
            await self._pool.aclose()

    def _circuit_is_open(self) -> bool:
        if self._consecutive_failures >= self._failure_threshold:
            if time.monotonic() < self._circuit_open_until:
                return True
            # Recovery window — allow a probe
            self._consecutive_failures = 0
        return False

    async def _record_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0

    async def _record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_open_until = time.monotonic() + self._recovery_timeout
                logger.warning("Redis circuit OPEN for %.0fs", self._recovery_timeout)

    async def get(self, key: str) -> str | None:
        """Get value. Returns None on any failure (graceful degradation)."""
        if self._circuit_is_open() or not self._client:
            return None
        try:
            result = await self._client.get(key)
            await self._record_success()
            return result
        except Exception:
            await self._record_failure()
            return None

    async def set(self, key: str, value: str) -> bool:
        """Set value. Returns False on failure."""
        if self._circuit_is_open() or not self._client:
            return False
        try:
            await self._client.set(key, value)
            await self._record_success()
            return True
        except Exception:
            await self._record_failure()
            return False

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        """Set with expiration (TTL in seconds)."""
        if self._circuit_is_open() or not self._client:
            return False
        try:
            await self._client.setex(key, ttl, value)
            await self._record_success()
            return True
        except Exception:
            await self._record_failure()
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key."""
        if self._circuit_is_open() or not self._client:
            return False
        try:
            await self._client.delete(key)
            await self._record_success()
            return True
        except Exception:
            await self._record_failure()
            return False

    async def publish(self, channel: str, message: str) -> bool:
        """Pub/Sub publish (replaces Azure Event Grid)."""
        if self._circuit_is_open() or not self._client:
            return False
        try:
            await self._client.publish(channel, message)
            await self._record_success()
            return True
        except Exception:
            await self._record_failure()
            return False

    async def incr(self, key: str, ttl: int | None = None) -> int | None:
        """Atomically increment an integer key. Set expiry on first write if ttl given."""
        if self._circuit_is_open() or not self._client:
            return None
        try:
            value = await self._client.incr(key)
            if ttl is not None and value == 1:
                await self._client.expire(key, ttl)
            await self._record_success()
            return int(value)
        except Exception:
            await self._record_failure()
            return None

    async def health_check(self) -> bool:
        """Ping Redis. Used by /health endpoint."""
        if not self._client:
            return False
        try:
            return await self._client.ping()
        except Exception:
            return False

    async def scan_keys(self, pattern: str, count: int = 100) -> list[str]:
        """SCAN for keys matching pattern. Safe for production (no KEYS command)."""
        if self._circuit_is_open() or not self._client:
            return []
        try:
            keys = []
            cursor = 0
            while True:
                cursor, batch = await self._client.scan(cursor, match=pattern, count=count)
                keys.extend(batch)
                if cursor == 0 or len(keys) >= count:
                    break
            await self._record_success()
            return keys[:count]
        except Exception:
            await self._record_failure()
            return []

    @property
    def is_circuit_open(self) -> bool:
        return self._circuit_is_open()
