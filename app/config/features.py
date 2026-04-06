"""Runtime feature flags — Redis-backed, toggleable without redeployment.

Microsoft pattern: azure-appconfiguration with 60s TTL.
Our equivalent: Redis hash with configurable TTL.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# In-memory cache (L1) for feature flags
_flag_cache: dict[str, Any] = {}


async def get_flag(redis_client, key: str, default: Any = None, ttl: int = 60) -> Any:
    """Get a feature flag value. Check L1 cache first, then Redis."""
    if key in _flag_cache:
        return _flag_cache[key]

    try:
        value = await redis_client.get(f"feature:{key}")
        if value is not None:
            parsed = json.loads(value)
            _flag_cache[key] = parsed
            return parsed
    except Exception:
        logger.debug("Feature flag Redis miss: %s", key)

    return default


async def set_flag(redis_client, key: str, value: Any, ttl: int = 0) -> None:
    """Set a feature flag. Updates both Redis and L1 cache."""
    _flag_cache[key] = value
    try:
        serialized = json.dumps(value)
        if ttl > 0:
            await redis_client.setex(f"feature:{key}", ttl, serialized)
        else:
            await redis_client.set(f"feature:{key}", serialized)
    except Exception:
        logger.warning("Failed to persist feature flag: %s", key)


def clear_cache() -> None:
    """Clear L1 feature flag cache. Called on config refresh."""
    _flag_cache.clear()
