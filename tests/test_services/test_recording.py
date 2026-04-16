"""Tests for call recording module (Phase 5 Blocker 2)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.recording import start_egress


class TestStartEgress:
    @pytest.mark.asyncio
    async def test_returns_none_when_recording_disabled(self):
        settings = MagicMock()
        settings.recording_enabled = False
        result = await start_egress(
            lk_api=MagicMock(),
            room_name="test-room",
            tenant_id="t1",
            call_id="c1",
            settings=settings,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_s3_credentials_missing(self):
        settings = MagicMock()
        settings.recording_enabled = True
        settings.s3_access_key = ""
        settings.s3_secret_key = ""
        result = await start_egress(
            lk_api=MagicMock(),
            room_name="test-room",
            tenant_id="t1",
            call_id="c1",
            settings=settings,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_failure_in_egress_does_not_raise(self):
        # start_egress must NEVER raise — recording is non-critical
        settings = MagicMock()
        settings.recording_enabled = True
        settings.s3_access_key = "key"
        settings.s3_secret_key = "secret"
        settings.s3_region = "fr-par"
        settings.s3_endpoint = "https://s3.fr-par.scw.cloud"
        settings.s3_recordings_bucket = "bucket"

        lk_api = MagicMock()
        lk_api.egress.start_room_composite_egress = AsyncMock(
            side_effect=RuntimeError("Egress worker unavailable")
        )

        # Must not raise
        result = await start_egress(
            lk_api=lk_api,
            room_name="test-room",
            tenant_id="t1",
            call_id="c1",
            settings=settings,
        )
        assert result is None
