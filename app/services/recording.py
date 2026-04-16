"""Call recording via LiveKit Egress → S3-compatible storage.

Phase 5 Blocker 2: RGPD-compliant call recording for French opticien calls.

Compliance:
- CNIL délibération 2005-019 + 2023 guidance: 6-month retention recommended
- Code de la santé publique L.1111-8: health data hosting requires HDS cert
- Recommended storage: Scaleway Paris (fr-par) — HDS-certified, French soil

Flow:
1. Call starts → start_egress() creates Room Composite audio-only recording
2. Recording writes to S3 bucket via LiveKit Egress worker
3. Call ends → LiveKit auto-stops egress when room empties
4. call_recordings row tracks egress_id, retention_until (180 days)
5. Nightly cron deletes expired rows + S3 lifecycle deletes objects
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def start_egress(
    *,
    lk_api: Any,
    room_name: str,
    tenant_id: str,
    call_id: str,
    supabase: Any = None,
    settings: Any = None,
) -> str | None:
    """Start a Room Composite egress for audio-only recording.

    Returns the egress_id or None if recording is disabled/fails.
    Failures are logged but NOT raised — recording is non-critical.
    """
    if not settings or not settings.recording_enabled:
        return None
    if not settings.s3_access_key or not settings.s3_secret_key:
        logger.warning("recording_enabled=true but S3 credentials missing — skipping egress")
        return None

    try:
        from livekit import api as lkapi

        output = lkapi.EncodedFileOutput(
            file_type=lkapi.EncodedFileType.OGG,
            filepath=f"recordings/{tenant_id}/{room_name}-{{time}}.ogg",
            s3=lkapi.S3Upload(
                access_key=settings.s3_access_key,
                secret=settings.s3_secret_key,
                region=settings.s3_region,
                bucket=settings.s3_recordings_bucket,
                endpoint=settings.s3_endpoint,
                force_path_style=True,  # required for Scaleway, Supabase, MinIO
            ),
        )
        egress_info = await lk_api.egress.start_room_composite_egress(
            lkapi.RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,  # no video track anyway; cheaper + no compositor
                layout="speaker",
                file_outputs=[output],
            )
        )
        egress_id = egress_info.egress_id
        logger.info("Recording started: room=%s egress_id=%s", room_name, egress_id)

        # Persist metadata (fire-and-forget)
        if supabase:
            import asyncio

            async def _persist():
                try:
                    await supabase.insert("call_recordings", {
                        "call_id": call_id,
                        "tenant_id": tenant_id,
                        "egress_id": egress_id,
                        "status": "recording",
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "consent_given": True,  # greeting includes disclosure
                    })
                except Exception as e:
                    logger.warning("Failed to persist call_recording: %s", e)

            asyncio.create_task(_persist())

        return egress_id

    except Exception as exc:
        # Never fail the call if recording fails
        logger.exception("Failed to start egress: %s", exc)
        return None
