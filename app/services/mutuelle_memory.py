"""Mutuelle memory service — persistent learning across calls.

Ported from OptiBot v1 tools/memory.py.
Before each call: load SVI path, astuces, pieges, interlocuteurs.
After each call: save learnings for future calls.
Uses Supabase RPC for atomic upserts.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.cache import TieredCache
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class MutuelleMemory:
    """Load and save mutuelle-specific learnings."""

    def __init__(self, supabase: SupabaseClient, cache: TieredCache):
        self._supabase = supabase
        self._cache = cache

    @staticmethod
    def _is_rpc_signature_mismatch(exc: Exception) -> bool:
        """Detect PostgREST RPC signature mismatch (safe to retry without tenant arg)."""
        msg = str(exc).lower()
        return (
            "pgrst202" in msg
            or ("could not find the function" in msg and "with parameters" in msg)
            or ("function" in msg and "does not exist" in msg and "tenant" in msg)
        )

    async def _rpc_with_tenant_fallback(
        self,
        function_name: str,
        params: dict[str, Any],
        tenant_id: str,
    ) -> Any:
        """Call RPC with tenant_id when supported; fall back to legacy signature when needed."""
        if not tenant_id:
            return await self._supabase.rpc(function_name, params)

        for tenant_param in ("tenant_id", "p_tenant_id"):
            tenant_params = dict(params)
            tenant_params[tenant_param] = tenant_id
            try:
                return await self._supabase.rpc(function_name, tenant_params)
            except Exception as e:
                if self._is_rpc_signature_mismatch(e):
                    continue
                raise

        return await self._supabase.rpc(function_name, params)

    async def load(self, mutuelle: str, tenant_id: str = "") -> dict[str, Any]:
        """Load memory for a mutuelle before call starts.

        Returns dict with: svi_chemin, horaires, astuces, pieges, interlocuteurs,
        total_appels, appels_reussis, delai_moyen_jours.
        """
        # Tenant-scoped cache key to prevent cross-tenant leakage
        safe_tenant = tenant_id or "global"
        cache_key = f"mutuelle_memory:{safe_tenant}:{mutuelle.lower().strip()}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        try:
            results = await self._rpc_with_tenant_fallback(
                "get_mutuelle_memory",
                {"nom_mutuelle": mutuelle.lower().strip()},
                tenant_id,
            )
            if results and isinstance(results, list) and len(results) > 0:
                memory = results[0]
            elif results and isinstance(results, dict):
                memory = results
            else:
                memory = {}
        except Exception as e:
            logger.warning("Failed to load mutuelle memory for %s: %s", mutuelle, e)
            memory = {}

        if memory:
            await self._cache.set(cache_key, memory, l1_ttl=300, l2_ttl=3600)

        return memory

    async def save(
        self,
        mutuelle: str,
        tenant_id: str,
        call_data: dict[str, Any],
    ) -> None:
        """Save learnings after a call.

        call_data should contain:
            svi_chemin, astuces (list[str]), pieges (list[str]),
            interlocuteur_nom, interlocuteur_role,
            delai_annonce, reference_mutuelle, resultat
        """
        nom = mutuelle.lower().strip()

        try:
            await self._rpc_with_tenant_fallback(
                "upsert_mutuelle_memory",
                {
                    "p_nom": nom,
                    "p_nom_affiche": mutuelle,
                    "p_svi_chemin": call_data.get("svi_chemin", ""),
                    "p_delai_jours": call_data.get("delai_annonce_jours", 0),
                    "p_interlocuteur_nom": call_data.get("interlocuteur_nom", ""),
                    "p_interlocuteur_role": call_data.get("interlocuteur_role", ""),
                },
                tenant_id,
            )
        except Exception as e:
            logger.warning("Failed to upsert mutuelle base data: %s", e)

        for astuce in call_data.get("astuces", []):
            try:
                await self._rpc_with_tenant_fallback(
                    "upsert_apprentissage",
                    {
                        "p_mutuelle_nom": nom,
                        "p_type": "astuce",
                        "p_contenu": astuce,
                    },
                    tenant_id,
                )
            except Exception as e:
                logger.warning("Failed to save astuce: %s", e)

        for piege in call_data.get("pieges", []):
            try:
                await self._rpc_with_tenant_fallback(
                    "upsert_apprentissage",
                    {
                        "p_mutuelle_nom": nom,
                        "p_type": "piege",
                        "p_contenu": piege,
                    },
                    tenant_id,
                )
            except Exception as e:
                logger.warning("Failed to save piege: %s", e)

        # Invalidate tenant-scoped cache
        safe_tenant = tenant_id or "global"
        await self._cache.delete(f"mutuelle_memory:{safe_tenant}:{nom}")

    def format_for_prompt(self, memory: dict[str, Any]) -> str:
        """Format memory dict into text for agent prompt injection."""
        if not memory:
            return ""

        parts = []
        if memory.get("svi_chemin"):
            parts.append(f"SVI: {memory['svi_chemin']}")
        if memory.get("horaires"):
            parts.append(f"Horaires: {memory['horaires']}")
        if memory.get("delai_moyen_jours"):
            parts.append(f"Delai moyen: {memory['delai_moyen_jours']} jours")
        if memory.get("numero_direct"):
            parts.append(f"Numero direct: {memory['numero_direct']}")

        astuces = memory.get("astuces", [])
        if astuces:
            items = [a.get("contenu", a) if isinstance(a, dict) else str(a) for a in astuces[:3]]
            parts.append(f"Astuces: {'; '.join(items)}")

        pieges = memory.get("pieges", [])
        if pieges:
            items = [p.get("contenu", p) if isinstance(p, dict) else str(p) for p in pieges[:3]]
            parts.append(f"Pieges a eviter: {'; '.join(items)}")

        interlocuteurs = memory.get("interlocuteurs", [])
        if interlocuteurs:
            items = []
            for i in interlocuteurs[:2]:
                if isinstance(i, dict):
                    items.append(f"{i.get('nom', '?')} ({i.get('role', '?')})")
                else:
                    items.append(str(i))
            parts.append(f"Contacts connus: {', '.join(items)}")

        stats = []
        if memory.get("total_appels"):
            stats.append(f"{memory['total_appels']} appels")
        if memory.get("appels_reussis"):
            stats.append(f"{memory['appels_reussis']} reussis")
        if stats:
            parts.append(f"Historique: {', '.join(stats)}")

        return "\n".join(parts)
