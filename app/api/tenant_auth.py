"""Multi-tenant authentication via hashed API keys.

Phase 5 Blocker 4: replaces the single global `settings.api_key` with per-tenant
lookup from `tenant_api_keys` table. Each tenant has one or more active API keys.

Compatibility:
- If `USE_MULTI_TENANT_AUTH=false` (default): falls back to settings.api_key behavior
- If `USE_MULTI_TENANT_AUTH=true`: requires valid Bearer key in tenant_api_keys

Usage in FastAPI route:

    @router.post("/api/call")
    async def initiate_call(
        request: CallRequest,
        tenant: TenantContext = Depends(require_tenant),
    ):
        # tenant.tenant_id is the authenticated tenant (ignore request.tenant_id)
        ...
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.config.settings import Settings

logger = logging.getLogger(__name__)
settings = Settings()


@dataclass
class TenantContext:
    """Authenticated tenant context, passed to route handlers via Depends."""

    tenant_id: str
    name: str = ""
    max_concurrent_calls: int = 5
    recording_enabled: bool = False
    consent_disclosure: str | None = None
    webhook_url: str | None = None
    key_prefix: str = ""  # first 12 chars of raw key, for log correlation

    @classmethod
    def default(cls) -> "TenantContext":
        """Single-tenant fallback (legacy behavior using settings.api_key)."""
        return cls(
            tenant_id="default",
            name=settings.default_tenant_name or "l'opticien",
            max_concurrent_calls=settings.max_concurrent_calls,
            recording_enabled=settings.recording_enabled,
            consent_disclosure=settings.default_consent_template or None,
            webhook_url=settings.webhook_url or None,
            key_prefix="legacy",
        )


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of raw API key — stored in tenant_api_keys.key_hash."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def require_tenant(authorization: str | None = Header(None)) -> TenantContext:
    """FastAPI dependency: authenticate request and return TenantContext.

    Modes:
    - use_multi_tenant_auth=False (default): single-tenant legacy mode.
      Accepts ONLY settings.api_key, returns TenantContext.default().
    - use_multi_tenant_auth=True: queries tenant_api_keys table.
      Supports multiple keys per tenant, last_used_at tracking.
    """
    if not authorization or not authorization.startswith("Bearer "):
        if settings.api_auth_required:
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        return TenantContext.default()

    raw = authorization[7:].strip()

    # Legacy single-tenant mode
    if not settings.use_multi_tenant_auth:
        if not settings.api_key:
            if settings.api_auth_required:
                raise HTTPException(status_code=503, detail="API auth required but no key configured")
            return TenantContext.default()
        if raw != settings.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return TenantContext.default()

    # Multi-tenant mode: lookup in Supabase
    from app.main import app_state

    if not app_state.supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured for multi-tenant auth")

    key_hash = hash_api_key(raw)
    try:
        rows = await app_state.supabase.select(
            "tenant_api_keys",
            {"key_hash": key_hash, "active": True},
            limit=1,
        )
    except Exception as e:
        logger.error("tenant_api_keys lookup failed: %s", e)
        raise HTTPException(status_code=503, detail="Auth backend error")

    if not rows:
        raise HTTPException(status_code=401, detail="Invalid API key")

    key_row = rows[0]
    tenant_rows = await app_state.supabase.select(
        "tenants", {"id": key_row["tenant_id"], "active": True}, limit=1
    )
    if not tenant_rows:
        raise HTTPException(status_code=403, detail="Tenant inactive")

    t = tenant_rows[0]
    ctx = TenantContext(
        tenant_id=t["id"],
        name=t.get("name", ""),
        max_concurrent_calls=int(t.get("max_concurrent_calls") or settings.max_concurrent_calls),
        recording_enabled=bool(t.get("recording_enabled", False)),
        consent_disclosure=t.get("consent_disclosure"),
        webhook_url=t.get("webhook_url"),
        key_prefix=raw[:12],
    )

    # Update last_used_at (fire-and-forget, don't block the request)
    import asyncio
    from datetime import datetime, timezone

    async def _update_last_used():
        try:
            await app_state.supabase.update(
                "tenant_api_keys",
                {"id": key_row["id"]},
                {"last_used_at": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:
            pass  # non-critical

    asyncio.create_task(_update_last_used())

    return ctx
