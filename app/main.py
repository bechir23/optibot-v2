"""OptiBot v2 — FastAPI + LiveKit AgentServer entrypoint.

Two servers run together:
1. FastAPI: /health, /api/call, /metrics (HTTP API)
2. LiveKit AgentServer: handles voice sessions (WebRTC/SIP)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.config.settings import Settings
from app.services.redis_client import RedisClient
from app.services.cache import TieredCache
from app.services.supabase_client import SupabaseClient
from app.services.embeddings import EmbeddingService
from app.services.rag import RAGService
from app.services.call_state_store import CallStateStore
from app.services.mutuelle_memory import MutuelleMemory
from app.services.action_policy import ActionPolicy
from app.services.config_registry import ConfigRegistry
from app.observability.metrics import (
    observe_rag_latency,
    record_call_failed,
    record_call_started,
)

logger = logging.getLogger(__name__)
settings = Settings()
_SHARED_VAD_MODEL: Any | None = None
_SHARED_VAD_LOCK = threading.Lock()


def _get_shared_vad_model() -> Any:
    """Load Silero VAD once per worker process to reduce per-call memory churn."""
    global _SHARED_VAD_MODEL
    if _SHARED_VAD_MODEL is None:
        with _SHARED_VAD_LOCK:
            if _SHARED_VAD_MODEL is None:
                from livekit.plugins import silero

                _SHARED_VAD_MODEL = silero.VAD.load()
    return _SHARED_VAD_MODEL


@dataclass
class AppState:
    redis: RedisClient | None = None
    cache: TieredCache | None = None
    supabase: SupabaseClient | None = None
    embeddings: EmbeddingService | None = None
    rag: RAGService | None = None
    call_state: CallStateStore | None = None
    mutuelle_memory: MutuelleMemory | None = None
    action_policy: ActionPolicy | None = None
    config_registry: ConfigRegistry | None = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.observability.logging import init_logging
    from app.observability.telemetry import init_telemetry

    init_logging(level=settings.log_level, json_output=not settings.debug)
    init_telemetry(otlp_endpoint=settings.otel_exporter_otlp_endpoint)

    # Redis
    app_state.redis = RedisClient(url=settings.redis_url)
    await app_state.redis.connect()
    app_state.cache = TieredCache(app_state.redis)

    # Supabase + Embeddings + RAG
    if settings.supabase_url and settings.supabase_key:
        app_state.supabase = SupabaseClient(url=settings.supabase_url, key=settings.supabase_key)
        app_state.embeddings = EmbeddingService(api_key=settings.openai_api_key, cache=app_state.cache)
        app_state.rag = RAGService(
            supabase=app_state.supabase,
            embeddings=app_state.embeddings,
            cache=app_state.cache,
        )
        app_state.mutuelle_memory = MutuelleMemory(supabase=app_state.supabase, cache=app_state.cache)
        app_state.action_policy = ActionPolicy(supabase=app_state.supabase, cache=app_state.cache)
        app_state.config_registry = ConfigRegistry(supabase=app_state.supabase, refresh_interval_sec=60.0)
        await app_state.config_registry.start()
        logger.info("Supabase + embeddings + RAG + memory + action policy + config registry initialized")

    # Build call-state store after optional Supabase wiring so durable audit writes work.
    app_state.call_state = CallStateStore(app_state.redis, supabase=app_state.supabase)

    logger.info("OptiBot v2 started on port %d", settings.port)
    yield

    if app_state.config_registry:
        await app_state.config_registry.stop()
    if app_state.supabase:
        await app_state.supabase.close()
    if app_state.redis:
        await app_state.redis.close()
    logger.info("OptiBot v2 shutdown")


app = FastAPI(
    title="OptiBot v2",
    description="Production Voice AI for French opticians",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else ["https://optibot.example.com"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

from app.api.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    TenantContextMiddleware,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=settings.max_concurrent_calls * 6, window_seconds=60)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(TenantContextMiddleware)

from app.api.routes import router
app.include_router(router)


def _parse_job_metadata(raw_metadata: str | None) -> dict[str, Any]:
    """Parse dispatch metadata safely.

    LiveKit dispatch metadata should be JSON, but shell quoting mistakes can produce
    escaped JSON payloads (for example, {\"tenant_id\":\"demo\"}).
    This parser recovers common escaped forms and never raises to the job entrypoint.
    """
    if not raw_metadata:
        return {}

    try:
        parsed = json.loads(raw_metadata)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        # Common shell artifact: JSON quotes escaped as \"...
        try:
            normalized = raw_metadata.replace('\\"', '"')
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                logger.warning("Recovered job metadata from escaped JSON payload")
                return parsed
        except Exception:
            pass

        parsed_loose = _parse_loose_metadata_object(raw_metadata)
        if parsed_loose is not None:
            logger.warning("Recovered job metadata from CLI loose-object payload")
            return parsed_loose

        logger.warning("Invalid job metadata payload; continuing with empty metadata")
        return {}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_loose_metadata_object(text: str) -> dict[str, Any] | None:
    """Parse non-JSON map-style metadata values.

    Handles payloads like:
    {tenant_id:demo,test_mode:inbound,caller_number:+33999}
    """
    s = text.strip()
    if not s.startswith("{") or not s.endswith("}"):
        return None

    n = len(s)

    def _skip_ws(i: int) -> int:
        while i < n and s[i].isspace():
            i += 1
        return i

    def _parse_quoted(i: int) -> tuple[str | None, int]:
        if i >= n or s[i] not in ('"', "'"):
            return None, i
        quote = s[i]
        i += 1
        start = i
        while i < n:
            if s[i] == quote and s[i - 1] != "\\":
                return s[start:i], i + 1
            i += 1
        return None, i

    def _convert_scalar(raw: str) -> Any:
        v = raw.strip()
        low = v.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low == "null":
            return None
        if v.isdigit():
            try:
                return int(v)
            except Exception:
                return v
        return v

    def _parse_object(i: int) -> tuple[dict[str, Any] | None, int]:
        if i >= n or s[i] != "{":
            return None, i

        i += 1
        obj: dict[str, Any] = {}

        while True:
            i = _skip_ws(i)
            if i >= n:
                return None, i
            if s[i] == "}":
                return obj, i + 1

            if s[i] in ('"', "'"):
                key, i = _parse_quoted(i)
                if key is None:
                    return None, i
            else:
                start = i
                while i < n and s[i] not in (":", "}"):
                    i += 1
                key = s[start:i].strip()
                if not key:
                    return None, i

            i = _skip_ws(i)
            if i >= n or s[i] != ":":
                return None, i
            i += 1
            i = _skip_ws(i)

            if i < n and s[i] == "{":
                value, i = _parse_object(i)
                if value is None:
                    return None, i
            elif i < n and s[i] in ('"', "'"):
                value, i = _parse_quoted(i)
                if value is None:
                    return None, i
            else:
                start = i
                while i < n and s[i] not in (",", "}"):
                    i += 1
                value = _convert_scalar(s[start:i])

            obj[key] = value

            i = _skip_ws(i)
            if i < n and s[i] == ",":
                i += 1
                continue
            if i < n and s[i] == "}":
                return obj, i + 1
            if i >= n:
                return None, i

    parsed, end = _parse_object(0)
    if parsed is None:
        return None
    end = _skip_ws(end)
    if end != n:
        return None
    return parsed


def _start_worker_heartbeat_thread() -> threading.Event | None:
    """Publish worker liveness in Redis so API /health can verify worker status.

    In cloud mode (CLOUD_MODE=true), skip heartbeat — LiveKit Cloud manages lifecycle.
    """
    if settings.cloud_mode:
        logger.info("Cloud mode: skipping Redis heartbeat (LiveKit Cloud manages worker lifecycle)")
        return None
    stop_event = threading.Event()
    heartbeat_key = settings.worker_heartbeat_key
    interval = max(1.0, settings.worker_heartbeat_interval_sec)
    ttl = max(settings.worker_heartbeat_ttl_sec, int(interval) + 1)

    async def _heartbeat_loop() -> None:
        redis = RedisClient(url=settings.redis_url)
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        consecutive_failures = 0
        last_failure_log = 0.0

        try:
            await redis.connect()
            logger.info("Worker heartbeat started: key=%s worker_id=%s", heartbeat_key, worker_id)

            while not stop_event.is_set():
                payload = json.dumps({"worker_id": worker_id, "ts": time.time()})
                ok = await redis.setex(heartbeat_key, ttl, payload)
                if ok:
                    if consecutive_failures:
                        logger.info(
                            "Worker heartbeat recovered after %d failed attempt(s)",
                            consecutive_failures,
                        )
                        consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    now = time.monotonic()
                    if now - last_failure_log >= max(interval, 30.0):
                        if redis.is_circuit_open:
                            logger.warning(
                                "Worker heartbeat paused: Redis circuit open (consecutive_failures=%d)",
                                consecutive_failures,
                            )
                        else:
                            logger.warning(
                                "Failed to publish worker heartbeat (consecutive_failures=%d)",
                                consecutive_failures,
                            )
                        last_failure_log = now

                # Sleep in short slices to react quickly when shutdown is requested.
                elapsed = 0.0
                while elapsed < interval and not stop_event.is_set():
                    step = min(0.5, interval - elapsed)
                    await asyncio.sleep(step)
                    elapsed += step
        except Exception as e:
            logger.exception("Worker heartbeat crashed: %s", e)
        finally:
            await redis.close()

    def _runner() -> None:
        asyncio.run(_heartbeat_loop())

    thread = threading.Thread(target=_runner, name="worker-heartbeat", daemon=True)
    thread.start()
    return stop_event


# ── LiveKit Agent Server ───────────────────────────────


async def _restore_call_state(call_id: str) -> dict[str, Any] | None:
    """Try to restore existing call state from Redis for crash recovery."""
    if not app_state.call_state:
        return None
    try:
        existing = await app_state.call_state.get(call_id)
    except Exception as exc:
        logger.warning("Failed to read existing call state for %s: %s", call_id, exc)
        return None
    if not existing or existing.get("phase") in ("completed", "error"):
        return None
    return existing


async def outbound_session(ctx):
    """Handle one outbound call session."""
    from livekit import api, rtc
    from livekit.agents import AgentSession, inference, room_io
    from livekit.plugins import noise_cancellation

    from app.agents.outbound_caller import OutboundCallerAgent
    from app.agents.ivr_navigator import IVRNavigatorAgent

    metadata = _parse_job_metadata(ctx.job.metadata)
    phone_number = metadata.get("phone_number")
    local_loopback = _coerce_bool(metadata.get("local_loopback", False))
    force_ivr = _coerce_bool(metadata.get("force_ivr", False))
    dossier = metadata.get("dossier", {})
    tenant_id = metadata.get("tenant_id", "default")
    mutuelle = dossier.get("mutuelle", "")
    call_accounted = False

    # Metrics: mark active call as soon as session starts.
    record_call_started(tenant_id=tenant_id, mutuelle=mutuelle)

    # Check for existing call state (crash recovery / reconnect)
    restored_state = await _restore_call_state(ctx.room.name)

    if app_state.call_state and restored_state is None:
        await app_state.call_state.initialize(
            call_id=ctx.room.name,
            tenant_id=tenant_id,
            mutuelle=dossier.get("mutuelle", ""),
        )
    elif app_state.call_state and restored_state is not None:
        logger.info("Restored outbound call state for %s at phase=%s", ctx.room.name, restored_state.get("phase"))
        await app_state.call_state.checkpoint(
            ctx.room.name,
            event="session_restored",
        )

    async def _dial_sip_participant() -> None:
        """Dial with retry while session is already booting in parallel."""
        nonlocal call_accounted

        if not phone_number:
            return

        sip_trunk_id = metadata.get("sip_trunk_id", settings.telnyx_sip_trunk_id)
        for attempt in range(3):
            try:
                await ctx.api.sip.create_sip_participant(
                    api.CreateSIPParticipantRequest(
                        room_name=ctx.room.name,
                        sip_trunk_id=sip_trunk_id,
                        sip_call_to=phone_number,
                        participant_identity=phone_number,
                        wait_until_answered=True,
                    )
                )
                logger.info("Outbound call answered: %s", phone_number)
                if app_state.call_state:
                    await app_state.call_state.mark_phase(ctx.room.name, "connected")

                @ctx.room.on("participant_attributes_changed")
                def _on_sip_status(changed: dict, participant: rtc.Participant):
                    sip_status = changed.get("sip.callStatus")
                    if sip_status:
                        logger.info("SIP status: %s for %s", sip_status, participant.identity)
                        if app_state.call_state:
                            asyncio.create_task(
                                app_state.call_state.mark_phase(
                                    ctx.room.name, sip_status, event=f"sip:{sip_status}"
                                )
                            )
                return
            except api.TwirpError as e:
                status = e.metadata.get("sip_status_code", "")
                sip_reason = e.metadata.get("sip_status", "")
                if attempt < 2 and str(status).startswith("5"):
                    logger.warning("SIP retry %d/3: %s", attempt + 1, e.message)
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue

                if str(status) in ("486", "600"):
                    reason = "busy"
                elif str(status) == "603":
                    reason = "declined"
                elif str(status) == "403":
                    sip_msg = str(sip_reason).lower()
                    if "blacklist" in sip_msg:
                        reason = "blacklisted"
                    elif "geo" in sip_msg or "international" in sip_msg:
                        reason = "geo_blocked"
                    elif "auth" in sip_msg or "credential" in sip_msg:
                        reason = "auth_failed"
                    else:
                        reason = "forbidden"
                elif str(status) in ("480", "408"):
                    reason = "unavailable"
                elif str(status) == "484":
                    reason = "address_incomplete"
                else:
                    reason = f"sip_{status or 'error'}"

                logger.error(
                    "SIP call failed: %s (status: %s %s, classified: %s)",
                    e.message,
                    status,
                    sip_reason,
                    reason,
                )
                record_call_failed(
                    tenant_id=tenant_id,
                    mutuelle=mutuelle,
                    reason=reason,
                )
                call_accounted = True
                if app_state.call_state:
                    await app_state.call_state.mark_error(ctx.room.name, str(e))
                raise

    # Load RAG context + mutuelle memory before session/dial so the initial prompt is complete.
    rag_context = {}
    mutuelle_memory = {}

    if app_state.rag and mutuelle:
        rag_start = time.monotonic()
        try:
            rag_context = await app_state.rag.retrieve_context(
                tenant_id=tenant_id,
                mutuelle=mutuelle,
                dossier_type=dossier.get("dossier_type", "optique"),
            )
            observe_rag_latency(time.monotonic() - rag_start)
        except Exception as e:
            observe_rag_latency(time.monotonic() - rag_start)
            logger.warning("RAG retrieval failed: %s", e)

    if app_state.mutuelle_memory and mutuelle:
        try:
            mutuelle_memory = await app_state.mutuelle_memory.load(mutuelle, tenant_id)
            if mutuelle_memory:
                memory_text = app_state.mutuelle_memory.format_for_prompt(mutuelle_memory)
                rag_context["mutuelle_memory"] = memory_text
                logger.info("Loaded mutuelle memory for %s", mutuelle)
        except Exception as e:
            logger.warning("Mutuelle memory load failed: %s", e)

    # Load dynamic action policy + mutuelle profile from DB (Phase 3)
    if app_state.action_policy and mutuelle:
        try:
            actions = await app_state.action_policy.load_actions(mutuelle, tenant_id)
            if actions:
                action_text = app_state.action_policy.format_actions_for_prompt(actions)
                rag_context["action_policy"] = action_text
                logger.info("Loaded %d action templates for %s", len(actions), mutuelle)
        except Exception as e:
            logger.debug("Action policy load: %s", e)

        try:
            profile = await app_state.action_policy.load_mutuelle_profile(mutuelle)
            if profile:
                rag_context["mutuelle_profile"] = profile
                if not mutuelle_memory.get("ivr_tree"):
                    ivr_data = profile.get("ivr_tree")
                    if isinstance(ivr_data, str):
                        import json as _json
                        try:
                            mutuelle_memory["ivr_tree"] = _json.loads(ivr_data)
                        except Exception:
                            mutuelle_memory["ivr_tree"] = {"notes": ivr_data}
                    elif isinstance(ivr_data, dict):
                        mutuelle_memory["ivr_tree"] = ivr_data
                logger.info("Loaded mutuelle profile for %s", mutuelle)
        except Exception as e:
            logger.debug("Mutuelle profile load: %s", e)

    # Optional local testing override: inject IVR tree directly from dispatch metadata.
    metadata_ivr_tree = metadata.get("known_ivr_tree")
    if isinstance(metadata_ivr_tree, dict):
        mutuelle_memory["ivr_tree"] = metadata_ivr_tree
    elif isinstance(metadata_ivr_tree, str) and metadata_ivr_tree.strip():
        mutuelle_memory["ivr_tree"] = {"notes": metadata_ivr_tree.strip()}

    # Prepare outbound caller agent kwargs (used by both IVR handoff and direct path)
    caller_kwargs: dict[str, Any] = dict(
        patient_name=dossier.get("patient_name", ""),
        patient_dob=dossier.get("patient_dob", ""),
        mutuelle=mutuelle,
        dossier_ref=dossier.get("dossier_ref", ""),
        montant=dossier.get("montant", 0),
        nir=dossier.get("nir", ""),
        dossier_type=dossier.get("dossier_type", "optique"),
        rag_context=rag_context,
        tenant_id=tenant_id,
        call_id=ctx.room.name,
        call_state_store=app_state.call_state,
        rag_service=app_state.rag,
    )

    # Choose agent: IVR navigator (if IVR map exists) or direct conversation
    ivr_tree = mutuelle_memory.get("ivr_tree") or mutuelle_memory.get("svi_chemin")
    known_ivr = None
    if isinstance(ivr_tree, dict):
        known_ivr = ivr_tree
    elif isinstance(ivr_tree, str) and ivr_tree:
        known_ivr = {"notes": ivr_tree}

    target_service = str(metadata.get("target_service", "remboursements optiques")).strip()
    use_ivr = (known_ivr is not None and bool(phone_number)) or force_ivr

    if use_ivr:
        agent = IVRNavigatorAgent(
            target_service=target_service or "remboursements optiques",
            max_attempts=settings.max_ivr_attempts,
            known_ivr_tree=known_ivr,
            tenant_id=tenant_id,
            mutuelle=mutuelle,
            caller_agent_kwargs=caller_kwargs,
        )
        logger.info("Starting with IVR navigator for %s (force_ivr=%s)", mutuelle, force_ivr)
        if app_state.call_state:
            await app_state.call_state.mark_phase(ctx.room.name, "ivr")
    else:
        agent = OutboundCallerAgent(**caller_kwargs)
        logger.info("Starting with direct conversation for %s", mutuelle)

    # Build per-call keyterms from comprehensive vocabulary database
    from app.pipeline.keyterm_builder import build_keyterms
    keyterms = build_keyterms(
        mutuelle=mutuelle,
        dossier_type=dossier.get("dossier_type", "optique"),
    )

    def _nc_selector(params):
        kind = getattr(getattr(params, "participant", None), "kind", None)
        if kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return noise_cancellation.BVCTelephony()
        return noise_cancellation.BVC()

    tts_kwargs: dict[str, Any] = {"language": "fr"}
    if settings.cartesia_voice_id:
        tts_kwargs["voice"] = settings.cartesia_voice_id

    try:
        stt_model: Any = inference.STT(
            model=f"deepgram/{settings.deepgram_model}",
            language=settings.deepgram_language,
            extra_kwargs={"keyterm": keyterms},
        )
        llm_model: Any = inference.LLM(model=settings.llm_model)
        tts_model: Any = inference.TTS(
            model=f"{settings.tts_provider}/{settings.cartesia_model}",
            **tts_kwargs,
        )
    except Exception as e:
        # Compatibility fallback for self-host/local environments without inference routing.
        from livekit.plugins import deepgram as deepgram_stt

        logger.warning("Inference init failed; using direct providers: %s", e)
        stt_model = deepgram_stt.STT(
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            keyterm=keyterms,
        )
        llm_model = settings.llm_model
        tts_model = (
            f"{settings.tts_provider}/{settings.cartesia_model}:{settings.cartesia_voice_id}"
            if settings.cartesia_voice_id
            else f"{settings.tts_provider}/{settings.cartesia_model}"
        )

    session = AgentSession(
        stt=stt_model,
        llm=llm_model,
        tts=tts_model,
        vad=_get_shared_vad_model(),
        turn_handling={
            "turn_detection": "stt",
            "endpointing": {
                "mode": "dynamic",   # adapts to conversation rhythm
                "min_delay": 0.0,    # Deepgram handles endpointing (LiveKit #4325)
                "max_delay": 3.0,    # cap for slow speakers
            },
            "interruption": {
                "enabled": True,
                "mode": "adaptive",  # context-aware barge-in detection
                "resume_false_interruption": True,  # resume after false interrupt
                "false_interruption_timeout": 1.5,
                "min_words": 2,      # require 2+ words to interrupt
            },
        },
        # Disable user_away_timeout — we have custom HoldDetector;
        # default 15s triggers false "away" during hold (docs gap)
        user_away_timeout=None,
        # Default max_tool_steps=3 is too low for 15+ tools;
        # agent may need: give_patient_name -> give_dossier_reference ->
        # ask_reimbursement_status -> extract_information in sequence
        max_tool_steps=8,
        preemptive_generation=True,
    )

    dial_task: asyncio.Task | None = None
    try:
        # Start the session first, then dial in parallel so first callee words are captured.
        session_started = asyncio.create_task(
            session.start(
                agent=agent,
                room=ctx.room,
                room_output_options=room_io.RoomOutputOptions(
                    transcription_enabled=True,
                    # Use 24kHz for higher quality TTS output;
                    # helps reduce artifacts during SIP transcoding (LiveKit SIP #608)
                    audio_sample_rate=24000,
                ),
                room_options=room_io.RoomOptions(
                    audio_input=room_io.AudioInputOptions(
                        noise_cancellation=_nc_selector,
                    ),
                ),
            )
        )

        if phone_number:
            dial_task = asyncio.create_task(_dial_sip_participant())

        await session_started

        if phone_number:
            if dial_task:
                await dial_task
        elif local_loopback:
            logger.info(
                "Local loopback outbound mode enabled for room=%s (no SIP dial)",
                ctx.room.name,
            )
            if app_state.call_state:
                await app_state.call_state.mark_phase(
                    ctx.room.name,
                    "connected",
                    event="local_loopback",
                )

    except Exception as e:
        if dial_task and not dial_task.done():
            dial_task.cancel()
            with suppress(asyncio.CancelledError):
                await dial_task
        logger.exception("Failed to start agent session: %s", e)
        if not call_accounted:
            record_call_failed(
                tenant_id=tenant_id,
                mutuelle=mutuelle,
                reason="session_start_error",
            )
            call_accounted = True
        if app_state.call_state:
            await app_state.call_state.mark_error(ctx.room.name, f"session_start:{e}")
        ctx.shutdown()
        raise

    # Phase 4: TTS first-audio metric via supported agent_state transitions.
    _tts_turn_start: dict[str, float] = {}
    from livekit.agents.voice.events import AgentStateChangedEvent

    @session.on("agent_state_changed")
    def _on_agent_state_metric(ev: AgentStateChangedEvent):
        if ev.old_state != "speaking" and ev.new_state == "speaking":
            _tts_turn_start["last"] = time.monotonic()
            return

        if ev.old_state == "speaking" and ev.new_state != "speaking":
            start = _tts_turn_start.pop("last", None)
            if start:
                from app.observability.metrics import observe_tts_first_audio_latency_ms
                observe_tts_first_audio_latency_ms((time.monotonic() - start) * 1000.0)

    # Phase 4: user disconnect detection + reason classification
    @session.on("user_state_changed")
    def _on_user_state(ev):
        if ev.new_state == "away":
            logger.info("User disconnected — will finalize on room close")

    # Participant disconnect reason mapping (for retry/escalation decisions)
    from livekit import rtc
    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnect(participant: rtc.Participant):
        reason = getattr(participant, 'disconnect_reason', 'unknown')
        logger.info("Participant %s disconnected: reason=%s", participant.identity, reason)
        if app_state.call_state:
            asyncio.create_task(
                app_state.call_state.mark_phase(
                    ctx.room.name,
                    f"participant_left",
                    event=f"disconnect:{participant.identity}:{reason}",
                )
            )

    # AMD: wire answering machine detector into user state changes (outbound only)
    if phone_number:
        from app.pipeline.amd import AnsweringMachineDetector, AnsweredBy
        _amd = AnsweringMachineDetector()
        _amd_speech_start: float = 0

        @session.on("user_state_changed")
        def _on_user_state_amd(ev):
            nonlocal _amd_speech_start
            if _amd.is_decided:
                return
            if ev.new_state == "speaking":
                _amd.on_speech_start()
                _amd_speech_start = time.monotonic()
            elif ev.new_state == "listening" and _amd_speech_start > 0:
                duration_ms = (time.monotonic() - _amd_speech_start) * 1000
                _amd_speech_start = 0
                _amd.on_speech_end(duration_ms)
                result = _amd.get_result()
                if result.answered_by == AnsweredBy.MACHINE_START:
                    logger.warning("AMD: voicemail detected (%.0fms speech) — hanging up", duration_ms)
                    if app_state.call_state:
                        asyncio.create_task(
                            app_state.call_state.mark_phase(ctx.room.name, "voicemail", event="amd:machine")
                        )
                    # Hang up — don't leave agent running against a voicemail greeting
                    async def _hangup_voicemail():
                        try:
                            await ctx.api.room.delete_room(
                                api.DeleteRoomRequest(room=ctx.room.name)
                            )
                        except Exception as exc:
                            logger.error("Failed to hangup after voicemail: %s", exc)
                    asyncio.create_task(_hangup_voicemail())
                elif result.answered_by == AnsweredBy.HUMAN:
                    logger.info("AMD: human detected (%.0fms speech)", duration_ms)
                    if app_state.call_state:
                        asyncio.create_task(
                            app_state.call_state.mark_phase(ctx.room.name, "human_answered", event="amd:human")
                        )

    # For outbound: let mutuelle agent speak first
    if phone_number is None:
        await session.generate_reply()

    # End-of-session finalization: ensure RAG writeback on all exit paths
    @ctx.room.on("disconnected")
    def on_disconnect():
        async def _finalize_on_disconnect() -> None:
            nonlocal call_accounted

            if call_accounted:
                return

            finalizable_agent = agent
            if isinstance(agent, IVRNavigatorAgent) and agent.handoff_agent is not None:
                finalizable_agent = agent.handoff_agent

            if isinstance(finalizable_agent, OutboundCallerAgent):
                extracted = finalizable_agent.extracted_data
                if not extracted.get("call_outcome"):
                    extracted["call_outcome"] = "disconnected"
                try:
                    await finalizable_agent._finalize_call()
                except Exception as e:
                    logger.exception("Call finalization failed on disconnect: %s", e)
                    record_call_failed(
                        tenant_id=tenant_id,
                        mutuelle=mutuelle,
                        reason="disconnect_finalize_error",
                    )
                    if app_state.call_state:
                        await app_state.call_state.mark_error(ctx.room.name, f"disconnect_finalize:{e}")
            else:
                record_call_failed(
                    tenant_id=tenant_id,
                    mutuelle=mutuelle,
                    reason="disconnected_before_handoff",
                )
                if app_state.call_state:
                    await app_state.call_state.mark_phase(
                        ctx.room.name,
                        "completed",
                        event="disconnected_before_handoff",
                    )

            call_accounted = True

        asyncio.create_task(_finalize_on_disconnect())


async def inbound_session(ctx):
    """Handle one inbound call session (receptionist mode).

    Triggered by LiveKit dispatch rule when inbound SIP call arrives.
    LiveKit Cloud routes: SIP trunk -> dispatch rule -> room -> this agent.
    """
    from livekit import rtc
    from livekit.agents import AgentSession, inference, room_io
    from livekit.plugins import noise_cancellation

    from app.agents.outbound_caller import OutboundCallerAgent

    # For inbound: metadata comes from dispatch rule, not API call
    metadata = _parse_job_metadata(ctx.job.metadata)
    tenant_id = metadata.get("tenant_id", "default")
    caller_number = metadata.get("caller_number", "")

    record_call_started(tenant_id=tenant_id, mutuelle="inbound")

    restored_state = await _restore_call_state(ctx.room.name)

    if app_state.call_state and restored_state is None:
        await app_state.call_state.initialize(
            call_id=ctx.room.name,
            tenant_id=tenant_id,
            mutuelle="inbound",
            phase="ringing",
        )
    elif app_state.call_state and restored_state is not None:
        logger.info("Restored inbound call state for %s at phase=%s", ctx.room.name, restored_state.get("phase"))
        await app_state.call_state.checkpoint(
            ctx.room.name,
            event="session_restored",
        )

    # Inbound agent: receptionist mode — greet caller, identify purpose, route
    agent = OutboundCallerAgent(
        patient_name="",
        mutuelle="",
        dossier_ref="",
        montant=0,
        dossier_type="optique",
        rag_context={},
        tenant_id=tenant_id,
        call_id=ctx.room.name,
        call_state_store=app_state.call_state,
        rag_service=app_state.rag,
    )

    from app.pipeline.keyterm_builder import build_keyterms
    keyterms = build_keyterms(dossier_type="optique")

    def _nc_selector(params):
        kind = getattr(getattr(params, "participant", None), "kind", None)
        if kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return noise_cancellation.BVCTelephony()
        return noise_cancellation.BVC()

    tts_kwargs: dict[str, Any] = {"language": "fr"}
    if settings.cartesia_voice_id:
        tts_kwargs["voice"] = settings.cartesia_voice_id

    try:
        stt_model: Any = inference.STT(
            model=f"deepgram/{settings.deepgram_model}",
            language=settings.deepgram_language,
            extra_kwargs={"keyterm": keyterms},
        )
        llm_model: Any = inference.LLM(model=settings.llm_model)
        tts_model: Any = inference.TTS(
            model=f"{settings.tts_provider}/{settings.cartesia_model}",
            **tts_kwargs,
        )
    except Exception as e:
        from livekit.plugins import deepgram as deepgram_stt

        logger.warning("Inference init failed; using direct providers: %s", e)
        stt_model = deepgram_stt.STT(
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            keyterm=keyterms,
        )
        llm_model = settings.llm_model
        tts_model = (
            f"{settings.tts_provider}/{settings.cartesia_model}:{settings.cartesia_voice_id}"
            if settings.cartesia_voice_id
            else f"{settings.tts_provider}/{settings.cartesia_model}"
        )

    session = AgentSession(
        stt=stt_model,
        llm=llm_model,
        tts=tts_model,
        vad=_get_shared_vad_model(),
        turn_handling={
            "turn_detection": "stt",
            "endpointing": {
                "mode": "dynamic",
                "min_delay": 0.0,
                "max_delay": 3.0,
            },
            "interruption": {
                "enabled": True,
                "mode": "adaptive",
                "resume_false_interruption": True,
                "false_interruption_timeout": 1.5,
                "min_words": 2,
            },
        },
        user_away_timeout=None,
        max_tool_steps=8,
        preemptive_generation=True,
    )

    await session.start(
        room=ctx.room,
        agent=agent,
        room_output_options=room_io.RoomOutputOptions(
            transcription_enabled=True,
            audio_sample_rate=24000,
        ),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=_nc_selector,
            ),
        ),
    )

    await ctx.connect()

    # Inbound: agent greets first
    await session.generate_reply()

    @ctx.room.on("disconnected")
    def on_disconnect():
        async def _finalize_on_disconnect() -> None:
            if not agent.extracted_data.get("call_outcome"):
                agent._extracted["call_outcome"] = "inbound_disconnected"
            try:
                await agent._finalize_call()
            except Exception as e:
                logger.exception("Inbound finalization failed: %s", e)

        asyncio.create_task(_finalize_on_disconnect())


async def unified_session(ctx):
    """Route to outbound or inbound based on metadata.

    LiveKit AgentServer only supports one rtc_session.
    Must be a top-level function (multiprocessing pickling requirement).
    """
    metadata = _parse_job_metadata(ctx.job.metadata)
    phone_number = metadata.get("phone_number")
    local_loopback = _coerce_bool(metadata.get("local_loopback", False))

    if phone_number or local_loopback:
        await outbound_session(ctx)
    else:
        await inbound_session(ctx)


def create_agent_server():
    """Create the LiveKit AgentServer with telephony support."""
    from livekit.agents import AgentServer

    server = AgentServer()
    server.rtc_session(agent_name=settings.agent_name)(unified_session)
    return server


async def dispatch_outbound_call(
    phone_number: str,
    dossier: dict,
    tenant_id: str = "default",
    sip_trunk_id: str = "",
) -> str:
    """Dispatch an outbound call agent via LiveKit API."""
    from livekit import api as lkapi

    lk = lkapi.LiveKitAPI(
        url=settings.livekit_url.replace("ws://", "http://").replace("wss://", "https://"),
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    safe_tenant = tenant_id.replace(" ", "_")[:32]
    room_name = f"optician-{safe_tenant}-{''.join(str(random.randint(0, 9)) for _ in range(10))}"

    metadata = json.dumps({
        "phone_number": phone_number,
        "dossier": dossier,
        "tenant_id": tenant_id,
        "sip_trunk_id": sip_trunk_id or settings.telnyx_sip_trunk_id,
    })

    try:
        await lk.agent_dispatch.create_dispatch(
            lkapi.CreateAgentDispatchRequest(
                agent_name=settings.agent_name,
                room=room_name,
                metadata=metadata,
            )
        )
        return room_name
    finally:
        await lk.aclose()


if __name__ == "__main__":
    from livekit.agents import cli

    heartbeat_stop: threading.Event | None = None
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        heartbeat_stop = _start_worker_heartbeat_thread()

    server = create_agent_server()
    try:
        cli.run_app(server)
    finally:
        if heartbeat_stop:
            heartbeat_stop.set()
