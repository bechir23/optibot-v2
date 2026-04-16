"""Tests for multi-tenant authentication (Phase 5 Blocker 4)."""
import os

import pytest
from fastapi import HTTPException

from app.api.tenant_auth import TenantContext, hash_api_key


class TestHashApiKey:
    def test_deterministic(self):
        assert hash_api_key("opti_abc123") == hash_api_key("opti_abc123")

    def test_different_keys_different_hashes(self):
        assert hash_api_key("opti_abc123") != hash_api_key("opti_abc124")

    def test_hex_64_chars(self):
        h = hash_api_key("opti_abc123")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestTenantContext:
    def test_default(self):
        ctx = TenantContext.default()
        assert ctx.tenant_id == "default"
        assert ctx.max_concurrent_calls >= 1
        assert ctx.recording_enabled is False
        assert ctx.key_prefix == "legacy"

    def test_custom_fields(self):
        ctx = TenantContext(
            tenant_id="acme",
            name="ACME Optique",
            max_concurrent_calls=20,
            recording_enabled=True,
            consent_disclosure="Custom disclosure",
            webhook_url="https://acme.example/webhook",
            key_prefix="opti_abc123",
        )
        assert ctx.tenant_id == "acme"
        assert ctx.max_concurrent_calls == 20
        assert ctx.recording_enabled is True
        assert ctx.webhook_url == "https://acme.example/webhook"


class TestRequireTenantLegacyMode:
    """Legacy single-tenant mode: use_multi_tenant_auth=False."""

    @pytest.mark.asyncio
    async def test_no_auth_header_when_not_required(self, monkeypatch):
        monkeypatch.setenv("USE_MULTI_TENANT_AUTH", "false")
        monkeypatch.setenv("API_AUTH_REQUIRED", "false")
        monkeypatch.setenv("API_KEY", "")

        # Reload settings + re-import to pick up env changes
        import importlib
        from app.api import tenant_auth
        importlib.reload(tenant_auth)

        ctx = await tenant_auth.require_tenant(authorization=None)
        assert ctx.tenant_id == "default"

    @pytest.mark.asyncio
    async def test_invalid_key_rejected(self, monkeypatch):
        monkeypatch.setenv("USE_MULTI_TENANT_AUTH", "false")
        monkeypatch.setenv("API_AUTH_REQUIRED", "true")
        monkeypatch.setenv("API_KEY", "correct-key")

        import importlib
        from app.api import tenant_auth
        importlib.reload(tenant_auth)

        with pytest.raises(HTTPException) as exc_info:
            await tenant_auth.require_tenant(authorization="Bearer wrong-key")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_key_returns_default_context(self, monkeypatch):
        monkeypatch.setenv("USE_MULTI_TENANT_AUTH", "false")
        monkeypatch.setenv("API_AUTH_REQUIRED", "true")
        monkeypatch.setenv("API_KEY", "correct-key")

        import importlib
        from app.api import tenant_auth
        importlib.reload(tenant_auth)

        ctx = await tenant_auth.require_tenant(authorization="Bearer correct-key")
        assert ctx.tenant_id == "default"
