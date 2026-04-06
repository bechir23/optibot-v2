"""Call state persistence — Redis (live) + Supabase (durable audit).

Redis: fast read/write for active call state, crash recovery, dashboard.
Supabase: durable call_log for post-call analysis, billing, compliance.
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from app.services.redis_client import RedisClient

if TYPE_CHECKING:
    from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class CallStateStore:
    """Redis-backed call state + optional Supabase durable audit."""

    def __init__(self, redis: RedisClient, ttl: int = 7200, supabase: "SupabaseClient | None" = None):
        self._redis = redis
        self._ttl = ttl
        self._supabase = supabase

    def _key(self, call_id: str) -> str:
        # call_id is room name: optician-{tenant}-{random} — already tenant-namespaced
        return f"call:{call_id}"

    async def list_active(self, tenant_id: str) -> list[dict]:
        """List active calls for a tenant (for dashboard)."""
        # Uses SCAN with pattern matching — safe for production
        pattern = f"call:optician-{tenant_id}-*"
        keys = await self._redis.scan_keys(pattern, count=100)
        results = []
        for key in keys:
            raw = await self._redis.get(key)
            if raw:
                state = json.loads(raw)
                if state.get("phase") not in ("completed", "error"):
                    results.append(state)
        return results

    async def initialize(self, call_id: str, tenant_id: str, mutuelle: str, phase: str = "dialing") -> None:
        state = {
            "call_id": call_id,
            "tenant_id": tenant_id,
            "mutuelle": mutuelle,
            "phase": phase,
            "tools_called": [],
            "events": [{"ts": time.time(), "event": "initialized"}],
            "started_at": time.time(),
        }
        await self._redis.setex(self._key(call_id), self._ttl, json.dumps(state))

        # Durable audit: write to Supabase call_log
        if self._supabase:
            try:
                await self._supabase.insert("call_log", {
                    "id": call_id,
                    "tenant_id": tenant_id,
                    "mutuelle": mutuelle,
                    "phone_number": "",
                    "direction": "outbound" if "optician-" in call_id else "inbound",
                    "status": phase,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
            except Exception as e:
                logger.debug("call_log insert: %s", e)

    async def mark_phase(self, call_id: str, phase: str, event: str = "") -> None:
        raw = await self._redis.get(self._key(call_id))
        if not raw:
            return
        state = json.loads(raw)
        state["phase"] = phase
        if event:
            state["events"].append({"ts": time.time(), "event": event})
        await self._redis.setex(self._key(call_id), self._ttl, json.dumps(state))

    async def append_tool_call(self, call_id: str, tool_name: str) -> None:
        raw = await self._redis.get(self._key(call_id))
        if not raw:
            return
        state = json.loads(raw)
        state["tools_called"].append(tool_name)
        await self._redis.setex(self._key(call_id), self._ttl, json.dumps(state))

    async def mark_error(self, call_id: str, error: str) -> None:
        raw = await self._redis.get(self._key(call_id))
        if not raw:
            return
        state = json.loads(raw)
        state["phase"] = "error"
        state["error"] = error
        state["events"].append({"ts": time.time(), "event": f"error:{error[:100]}"})
        await self._redis.setex(self._key(call_id), self._ttl, json.dumps(state))

    async def get(self, call_id: str) -> dict | None:
        raw = await self._redis.get(self._key(call_id))
        return json.loads(raw) if raw else None

    async def finalize(self, call_id: str, outcome: str, extracted: dict) -> None:
        raw = await self._redis.get(self._key(call_id))
        if not raw:
            return
        state = json.loads(raw)
        state["phase"] = "completed"
        state["outcome"] = outcome
        state["extracted"] = extracted
        state["duration_seconds"] = time.time() - state.get("started_at", time.time())
        state["events"].append({"ts": time.time(), "event": f"completed:{outcome}"})
        await self._redis.setex(self._key(call_id), self._ttl, json.dumps(state))

        # Durable audit: update call_log with outcome
        if self._supabase:
            try:
                await self._supabase.update("call_log", {"id": call_id}, {
                    "status": "completed",
                    "outcome": outcome,
                    "duration_seconds": state["duration_seconds"],
                    "extracted_data": json.dumps(extracted),
                    "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
            except Exception as e:
                logger.debug("call_log finalize: %s", e)
