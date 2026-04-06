"""RAG service — Supabase hybrid search with real embeddings.

Flow:
1. Check Redis cache (24h TTL)
2. Embed query with mistral-embed (1024-dim)
3. Call Supabase RPC for pgvector cosine similarity + text filter
4. Return key learnings + best action sequences
5. Cache result

Post-call: generate summary → embed → store for future retrieval.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.cache import TieredCache
from app.services.embeddings import EmbeddingService
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class RAGService:
    """Tenant-aware RAG with real vector embeddings."""

    def __init__(
        self,
        supabase: SupabaseClient,
        embeddings: EmbeddingService,
        cache: TieredCache,
    ):
        self._supabase = supabase
        self._embeddings = embeddings
        self._cache = cache

    async def retrieve_context(
        self,
        tenant_id: str,
        mutuelle: str,
        dossier_type: str = "optique",
        query: str = "",
    ) -> dict[str, Any]:
        """Retrieve context from similar past calls using vector search.

        Run during dial phase (while phone rings) = zero latency impact.
        """
        cache_key = f"rag:{tenant_id}:{mutuelle}:{dossier_type}"
        cached = await self._cache.get(cache_key)
        if cached:
            logger.debug("RAG cache hit: %s", cache_key)
            return cached

        search_query = query or f"{dossier_type} {mutuelle} remboursement optique"

        # Embed query with mistral-embed
        try:
            query_embedding = await self._embeddings.embed(search_query)
        except Exception as e:
            logger.warning("Embedding failed, falling back to text search: %s", e)
            query_embedding = None

        # Search Supabase — vector if available, text fallback
        try:
            if query_embedding:
                results = await self._supabase.rpc("match_call_summaries_vector", {
                    "query_embedding": query_embedding,
                    "filter_tenant": tenant_id,
                    "filter_mutuelle": mutuelle,
                    "match_count": 5,
                })
            else:
                results = await self._supabase.rpc("match_call_summaries", {
                    "query_text": search_query,
                    "filter_tenant": tenant_id,
                    "filter_mutuelle": mutuelle,
                    "match_count": 5,
                })
        except Exception as e:
            logger.warning("RAG retrieval failed: %s", e)
            return {}

        if not results:
            return {}

        all_learnings = []
        all_sequences = []
        resolved_count = 0

        for r in results:
            if isinstance(r.get("key_learnings"), list):
                all_learnings.extend(r["key_learnings"])
            if isinstance(r.get("action_sequence"), list):
                all_sequences.append(r["action_sequence"])
            if r.get("outcome") == "resolved":
                resolved_count += 1

        context = {
            "key_learnings": list(dict.fromkeys(all_learnings))[:5],
            "best_action_sequence": all_sequences[0] if all_sequences else [],
            "success_rate": resolved_count / len(results) if results else 0,
            "similar_calls": len(results),
        }

        await self._cache.set(cache_key, context, l1_ttl=300, l2_ttl=86400)
        return context

    async def store_call_summary(
        self,
        tenant_id: str,
        call_id: str,
        mutuelle: str,
        dossier_type: str,
        summary: str,
        outcome: str,
        key_learnings: list[str],
        action_sequence: list[str],
    ) -> None:
        """Store a call summary with embedding for future RAG retrieval."""
        try:
            embedding = await self._embeddings.embed(summary)
        except Exception as e:
            logger.warning("Failed to embed summary, storing without vector: %s", e)
            embedding = None

        data = {
            "tenant_id": tenant_id,
            "call_id": call_id,
            "mutuelle": mutuelle,
            "dossier_type": dossier_type,
            "summary": summary,
            "outcome": outcome,
            "key_learnings": key_learnings,
            "action_sequence": action_sequence,
        }
        if embedding:
            data["embedding"] = embedding

        try:
            await self._supabase.insert("call_summaries", data)
            logger.info("Stored call summary: %s (outcome=%s)", call_id, outcome)
        except Exception as e:
            logger.error("Failed to store call summary: %s", e)
