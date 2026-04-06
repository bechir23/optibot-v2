"""Supabase client — PostgreSQL + pgvector + RLS.

Handles all DB operations: dossier lookup, call persistence, RAG retrieval.
Uses httpx for async HTTP calls to Supabase REST API.
Writes use exponential backoff (3 attempts) to survive transient failures.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_WRITE_MAX_RETRIES = 3
_WRITE_BASE_DELAY = 0.5  # seconds


async def _retry_write(operation, *args, **kwargs) -> Any:
    """Execute a write operation with exponential backoff on transient failures."""
    last_exc = None
    for attempt in range(_WRITE_MAX_RETRIES):
        try:
            return await operation(*args, **kwargs)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            # Don't retry client errors (4xx) except 429 (rate limit)
            if isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            delay = _WRITE_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Supabase write attempt %d/%d failed: %s — retrying in %.1fs",
                attempt + 1, _WRITE_MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
    logger.error("Supabase write failed after %d attempts: %s", _WRITE_MAX_RETRIES, last_exc)
    raise last_exc


class SupabaseClient:
    """Async Supabase client using REST API (no SDK dependency)."""

    def __init__(self, url: str, key: str):
        self._url = url.rstrip("/")
        self._key = key
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{self._url}/rest/v1",
                headers=self._headers,
                timeout=15.0,
            )

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def rpc(self, function_name: str, params: dict) -> list[dict]:
        """Call a Supabase RPC function (for pgvector similarity search)."""
        await self._ensure_client()
        resp = await self._client.post(
            f"{self._url}/rest/v1/rpc/{function_name}",
            json=params,
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def select(self, table: str, filters: dict[str, str] | None = None, limit: int = 50) -> list[dict]:
        """Select rows from a table with optional filters."""
        await self._ensure_client()
        params = {"limit": str(limit)}
        if filters:
            for k, v in filters.items():
                params[k] = f"eq.{v}"
        resp = await self._client.get(f"/{table}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _insert_once(self, table: str, data: dict | list[dict]) -> list[dict]:
        """Single insert attempt."""
        await self._ensure_client()
        resp = await self._client.post(f"/{table}", json=data)
        resp.raise_for_status()
        return resp.json()

    async def insert(self, table: str, data: dict | list[dict]) -> list[dict]:
        """Insert row(s) into a table with retry on transient failures."""
        return await _retry_write(self._insert_once, table, data)

    async def _update_once(self, table: str, filters: dict[str, str], data: dict) -> list[dict]:
        """Single update attempt."""
        await self._ensure_client()
        params = {k: f"eq.{v}" for k, v in filters.items()}
        resp = await self._client.patch(f"/{table}", json=data, params=params)
        resp.raise_for_status()
        return resp.json()

    async def update(self, table: str, filters: dict[str, str], data: dict) -> list[dict]:
        """Update rows matching filters with retry on transient failures."""
        return await _retry_write(self._update_once, table, filters, data)

    async def select_tenant(
        self,
        table: str,
        tenant_id: str,
        filters: dict[str, str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Select with mandatory tenant_id filter — enforces data isolation.

        Use this instead of select() for any tenant-scoped data.
        Raises ValueError if tenant_id is empty (fail-closed).
        """
        if not tenant_id:
            raise ValueError(f"tenant_id required for {table} query — refusing to return unscoped data")
        merged = {"tenant_id": tenant_id}
        if filters:
            merged.update(filters)
        return await self.select(table, merged, limit)

    async def insert_tenant(self, table: str, tenant_id: str, data: dict | list[dict]) -> list[dict]:
        """Insert with mandatory tenant_id — enforces data isolation."""
        if not tenant_id:
            raise ValueError(f"tenant_id required for {table} insert")
        if isinstance(data, list):
            for row in data:
                row["tenant_id"] = tenant_id
        else:
            data["tenant_id"] = tenant_id
        return await self.insert(table, data)

    async def health_check(self) -> bool:
        try:
            await self._ensure_client()
            resp = await self._client.get("/", params={"limit": "1"})
            return resp.status_code < 500
        except Exception:
            return False
