"""Embeddings service — OpenAI text-embedding-3-small via direct HTTP.

OpenAI embeddings: 1536 dimensions, better multilingual quality than mistral-embed.
Direct httpx calls — no SDK dependency issues.
Cached in Redis for 24h.
"""
from __future__ import annotations

import hashlib
import logging

import httpx

from app.services.cache import TieredCache

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSION = 1536
OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"


class EmbeddingService:
    """Production embedding service — OpenAI text-embedding-3-small."""

    def __init__(self, api_key: str, cache: TieredCache | None = None):
        self._client = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        self._cache = cache

    async def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns 1536-dim vector. Cached 24h."""
        cache_key = f"embed:{hashlib.sha256(text.encode()).hexdigest()[:16]}"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                return cached

        resp = await self._client.post(
            OPENAI_EMBED_URL,
            json={"model": EMBED_MODEL, "input": text},
        )
        resp.raise_for_status()
        vector = resp.json()["data"][0]["embedding"]

        if self._cache:
            await self._cache.set(cache_key, vector, l1_ttl=300, l2_ttl=86400)

        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one API call."""
        if not texts:
            return []
        resp = await self._client.post(
            OPENAI_EMBED_URL,
            json={"model": EMBED_MODEL, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]

    async def close(self):
        await self._client.aclose()
