"""Action policy service — loads dynamic tool config from DB per mutuelle.

Reads action_templates and mutuelle_action_overrides from Supabase.
Creates LiveKit function_tools dynamically based on DB configuration.
Adapts tool descriptions and availability per mutuelle + tenant.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.cache import TieredCache
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class ActionPolicy:
    """Load and apply dynamic action policies from DB."""

    def __init__(self, supabase: SupabaseClient, cache: TieredCache):
        self._supabase = supabase
        self._cache = cache

    async def load_actions(self, mutuelle: str = "", tenant_id: str = "") -> list[dict]:
        """Load action templates, optionally with mutuelle-specific overrides.

        Returns list of dicts with: id, phase, template, description, success_rate
        """
        cache_key = f"actions:{tenant_id}:{mutuelle}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        try:
            base_actions = await self._supabase.select("action_templates", {"active": "true"}, limit=100)
        except Exception as e:
            logger.warning("Failed to load action templates: %s", e)
            return []

        overrides = {}
        if mutuelle:
            try:
                rows = await self._supabase.select(
                    "mutuelle_action_overrides",
                    {"mutuelle": mutuelle.lower()},
                    limit=100,
                )
                for row in rows:
                    overrides[row.get("action_id", "")] = row
            except Exception as e:
                logger.debug("No mutuelle overrides for %s: %s", mutuelle, e)

        result = []
        for action in base_actions:
            action_id = action.get("id", "")
            override = overrides.get(action_id, {})

            result.append({
                "id": action_id,
                "phase": action.get("phase", ""),
                "template": override.get("template_override") or action.get("template", ""),
                "description": action.get("description", ""),
                "success_rate": override.get("success_rate", 0.5),
                "sample_count": override.get("sample_count", 0),
            })

        if result:
            await self._cache.set(cache_key, result, l1_ttl=300, l2_ttl=3600)

        return result

    async def load_mutuelle_profile(self, mutuelle: str) -> dict[str, Any]:
        """Load mutuelle IVR map and metadata from DB.

        Returns dict with: ivr_tree, phone_number, avg_wait_minutes, best_call_time, notes
        """
        cache_key = f"mutuelle_profile:{mutuelle.lower()}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        try:
            rows = await self._supabase.select(
                "mutuelle_ivr_maps",
                {"mutuelle": mutuelle},
                limit=1,
            )
            if rows:
                profile = rows[0]
                await self._cache.set(cache_key, profile, l1_ttl=600, l2_ttl=7200)
                return profile
        except Exception as e:
            logger.debug("No mutuelle profile for %s: %s", mutuelle, e)

        return {}

    async def record_outcome(
        self,
        action_id: str,
        call_id: str,
        tenant_id: str,
        mutuelle: str,
        success: bool,
        confidence: float = 0.0,
    ) -> None:
        """Record action outcome for success rate tracking."""
        try:
            await self._supabase.insert("action_outcomes", {
                "action_id": action_id,
                "call_id": call_id,
                "tenant_id": tenant_id,
                "mutuelle": mutuelle.lower() if mutuelle else "",
                "success": success,
                "confidence": confidence,
            })
        except Exception as e:
            logger.warning("Failed to record action outcome: %s", e)

        # Invalidate cached actions to pick up new success rates
        await self._cache.delete(f"actions:{tenant_id}:{mutuelle}")

    def format_actions_for_prompt(self, actions: list[dict], phase: str = "") -> str:
        """Format loaded actions into prompt text with success rates.

        Used to inject dynamic action awareness into agent instructions.
        """
        if not actions:
            return ""

        filtered = actions
        if phase:
            filtered = [a for a in actions if a.get("phase") == phase]

        if not filtered:
            return ""

        lines = []
        for a in filtered[:10]:
            rate = a.get("success_rate", 0.5)
            count = a.get("sample_count", 0)
            suffix = f" [succes: {rate:.0%}, n={count}]" if count > 0 else ""
            lines.append(f"- {a['id']}: {a.get('description', '')}{suffix}")

        return "\n".join(lines)
