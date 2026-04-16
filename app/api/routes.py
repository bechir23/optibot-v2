"""API routes — /health, /api/call, /api/schedule, /metrics, /api/calls (ops)."""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header

from app.api.tenant_auth import TenantContext, require_tenant
from pydantic import BaseModel, field_validator

from app.config.settings import Settings

router = APIRouter()
settings = Settings()
logger = logging.getLogger(__name__)

# E.164 phone format: + followed by 1-15 digits
_PHONE_RE = re.compile(r"^\+[1-9]\d{1,14}$")


class CallRequest(BaseModel):
    phone: str
    dossier_id: str
    tenant_id: str
    patient_name: str = ""
    patient_dob: str = ""
    mutuelle: str = ""
    dossier_ref: str = ""
    montant: float = 0.0
    nir: str = ""
    dossier_type: str = "optique"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "").replace("-", "")
        if not _PHONE_RE.match(cleaned):
            raise ValueError(f"Invalid phone number: must be E.164 format (e.g. +33612345678)")
        return cleaned

    @field_validator("dossier_type")
    @classmethod
    def validate_dossier_type(cls, v: str) -> str:
        allowed = {"optique", "dentaire", "audioprothese", "general"}
        if v not in allowed:
            raise ValueError(f"Invalid dossier_type: must be one of {allowed}")
        return v

    @field_validator("montant")
    @classmethod
    def validate_montant(cls, v: float) -> float:
        if v < 0 or v > 100000:
            raise ValueError("Montant must be between 0 and 100000")
        return v

    @field_validator("nir")
    @classmethod
    def validate_nir(cls, v: str) -> str:
        if v and not re.match(r"^[12]\d{12,14}$", v.replace(" ", "")):
            raise ValueError("NIR must be 13-15 digits starting with 1 or 2")
        return v.replace(" ", "")


class HealthResponse(BaseModel):
    status: str
    redis: bool
    worker_registered: bool
    version: str = "0.1.0"
    config_version: int = 0
    config_mutuelles: int = 0


def _check_auth(authorization: str | None):
    if settings.api_auth_required and not settings.api_key:
        raise HTTPException(status_code=503, detail="API auth is required but no API key is configured")
    if settings.api_key and authorization != f"Bearer {settings.api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/health", response_model=HealthResponse)
async def health():
    from app.main import app_state
    redis_ok = await app_state.redis.health_check() if app_state.redis else False

    # In cloud mode: worker is managed by LiveKit Cloud, skip Redis heartbeat check
    if settings.cloud_mode:
        worker_registered = True  # LiveKit Cloud ensures worker is running
    elif app_state.redis:
        worker_registered = await app_state.redis.get(settings.worker_heartbeat_key) is not None
    else:
        worker_registered = False

    config_version = 0
    config_mutuelles = 0
    if app_state.config_registry:
        config_version = app_state.config_registry.version
        config_mutuelles = len(app_state.config_registry.known_mutuelles)

    return HealthResponse(
        status="healthy" if (redis_ok or settings.cloud_mode) and worker_registered else "degraded",
        redis=redis_ok,
        worker_registered=worker_registered,
        config_version=config_version,
        config_mutuelles=config_mutuelles,
    )


@router.post("/api/call")
async def initiate_call(
    request: CallRequest,
    tenant: TenantContext = Depends(require_tenant),
):
    # Tenant comes from authenticated API key — NOT from request body.
    # If caller sent a different tenant_id, log as a security warning.
    if request.tenant_id.strip() and request.tenant_id != tenant.tenant_id:
        logger.warning(
            "tenant_id mismatch: body=%s auth=%s key_prefix=%s",
            request.tenant_id, tenant.tenant_id, tenant.key_prefix,
        )

    if not request.phone.strip():
        raise HTTPException(status_code=400, detail="phone is required")
    if not request.mutuelle.strip():
        raise HTTPException(status_code=400, detail="mutuelle is required")

    dossier = {
        "patient_name": request.patient_name,
        "patient_dob": request.patient_dob,
        "mutuelle": request.mutuelle,
        "dossier_ref": request.dossier_ref,
        "montant": request.montant,
        "nir": request.nir,
        "dossier_type": request.dossier_type,
    }

    try:
        from app.main import dispatch_outbound_call
        room_name = await dispatch_outbound_call(
            phone_number=request.phone,
            dossier=dossier,
            tenant_id=tenant.tenant_id,
        )
        return {
            "status": "dispatched",
            "room": room_name,
            "phone": request.phone,
            "tenant_id": tenant.tenant_id,
        }
    except Exception as e:
        logger.error("Failed to dispatch call: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/schedule")
async def schedule_calls(
    requests: list[CallRequest],
    tenant: TenantContext = Depends(require_tenant),
):
    if not requests:
        raise HTTPException(status_code=400, detail="Empty request list")

    from app.main import dispatch_outbound_call

    results = []
    for req in requests:
        if req.tenant_id.strip() and req.tenant_id != tenant.tenant_id:
            logger.warning(
                "schedule tenant_id mismatch: body=%s auth=%s",
                req.tenant_id, tenant.tenant_id,
            )
        try:
            room = await dispatch_outbound_call(
                phone_number=req.phone,
                dossier={
                    "patient_name": req.patient_name,
                    "patient_dob": req.patient_dob,
                    "mutuelle": req.mutuelle,
                    "dossier_ref": req.dossier_ref,
                    "montant": req.montant,
                    "nir": req.nir,
                    "dossier_type": req.dossier_type,
                },
                tenant_id=tenant.tenant_id,
            )
            results.append({"dossier_id": req.dossier_id, "status": "dispatched", "room": room})
        except Exception as e:
            results.append({"dossier_id": req.dossier_id, "status": "error", "detail": str(e)})

    return {"scheduled": len([r for r in results if r["status"] == "dispatched"]), "results": results}


@router.get("/metrics")
async def prometheus_metrics():
    from fastapi.responses import PlainTextResponse
    from prometheus_client import generate_latest
    return PlainTextResponse(content=generate_latest(), media_type="text/plain")


# ═══════════════════════════════════════════════════════════════════════
# Phase 5 Blocker 3: Ops UI endpoints (read-only, per-tenant)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/api/calls")
async def list_calls(
    tenant: TenantContext = Depends(require_tenant),
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    mutuelle: str | None = None,
):
    """List recent calls for the authenticated tenant."""
    from app.main import app_state

    if not app_state.supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    filters: dict[str, Any] = {"tenant_id": tenant.tenant_id}
    if status:
        filters["outcome"] = status
    if mutuelle:
        filters["mutuelle"] = mutuelle

    try:
        rows = await app_state.supabase.select(
            "call_log", filters, limit=min(limit, 200),
        )
        return {"total": len(rows), "calls": rows}
    except Exception as e:
        logger.error("list_calls failed: %s", e)
        raise HTTPException(status_code=500, detail="Query failed")


@router.get("/api/calls/{call_id}")
async def get_call(
    call_id: str,
    tenant: TenantContext = Depends(require_tenant),
):
    """Get call details + transcript for the authenticated tenant."""
    from app.main import app_state

    if not app_state.supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        call_rows = await app_state.supabase.select(
            "call_log", {"id": call_id, "tenant_id": tenant.tenant_id}, limit=1,
        )
        if not call_rows:
            raise HTTPException(status_code=404, detail="Call not found")

        transcript_rows = await app_state.supabase.select(
            "call_transcript", {"call_id": call_id, "tenant_id": tenant.tenant_id}, limit=500,
        )
        recording_rows = await app_state.supabase.select(
            "call_recordings", {"call_id": call_id, "tenant_id": tenant.tenant_id}, limit=1,
        )

        return {
            "call": call_rows[0],
            "transcript": sorted(transcript_rows, key=lambda r: r.get("ts_ms", 0)),
            "recording": recording_rows[0] if recording_rows else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_call failed: %s", e)
        raise HTTPException(status_code=500, detail="Query failed")
