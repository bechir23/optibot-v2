"""Centralized configuration — all env vars, no hardcoded values."""
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """OptiBot v2 settings. Every value is overridable via environment variable."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── LiveKit ──────────────────────────────────────
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    # ── LLM providers ────────────────────────────────
    mistral_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = "openai/gpt-4.1-mini"
    llm_fallback_model: str = "mistral-small-latest"

    # When True, bypass LiveKit's inference proxy and use direct provider
    # connections (Deepgram/Cartesia/OpenAI). Required when LiveKit Cloud
    # gateway credits are exhausted (MaxGatewayCredits quota error).
    use_direct_providers: bool = False

    # ── STT / TTS ────────────────────────────────────
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "fr"
    cartesia_api_key: str = ""
    cartesia_voice_id: str = ""
    cartesia_model: str = "sonic-3"
    tts_provider: str = "cartesia"

    # Deepgram keyterm prompting — loaded from data/deepgram_keyterms.json
    # Per-call vocabulary built dynamically by app.pipeline.keyterm_builder
    # Max: 100 keyterms, 500 tokens per request (Deepgram Nova-3 limit)

    # ── Telephony ────────────────────────────────────
    telnyx_api_key: str = ""
    livekit_sip_outbound_trunk_id: str = ""
    telnyx_sip_trunk_id: str = ""
    telnyx_username: str = ""
    sip_destination_country: str = "FR"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ── Database ─────────────────────────────────────
    supabase_url: str = ""
    supabase_key: str = ""

    # ── Infrastructure ───────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # Worker heartbeat key used by /health to reflect real worker liveness.
    worker_heartbeat_key: str = "worker:heartbeat"
    worker_heartbeat_ttl_sec: int = 30
    worker_heartbeat_interval_sec: float = 10.0

    # Cloud mode: when True, skip Redis heartbeat (cloud manages worker lifecycle)
    cloud_mode: bool = False

    # Agent name for LiveKit registration (must match dispatch rules)
    agent_name: str = "optibot"

    # ── Tenant defaults (used when no per-tenant override) ──
    # Compliance: EU AI Act Art. 50 + RGPD Art. 13 + CNIL délibération 2023-094.
    # Tenant name appears in the consent disclosure: "Bonjour, je suis un
    # assistant vocal automatise du cabinet d'optique {tenant_name}."
    default_tenant_name: str = ""
    # Optional override template — use {tenant_name} placeholder. Leave empty to
    # use the default ("Bonjour, je suis un assistant vocal automatise...").
    default_consent_template: str = ""

    # ── Security ─────────────────────────────────────
    api_key: str = ""
    api_auth_required: bool = True
    dossier_encryption_key: str = ""
    # Phase 5 Blocker 4: when True, API auth queries tenant_api_keys table
    # instead of matching the single global api_key. Required for >1 customer.
    use_multi_tenant_auth: bool = False

    # ── Feature flags (Microsoft pattern: runtime-tunable) ──
    answer_soft_timeout_sec: float = 4.0
    answer_hard_timeout_sec: float = 15.0
    phone_silence_timeout_sec: float = 20.0
    participant_join_timeout_sec: float = 60.0
    max_ivr_attempts: int = 5
    max_concurrent_calls: int = 10
    recording_enabled: bool = False
    # Phase 5 Blocker 2: S3-compatible storage for call recordings.
    # Recommended: Scaleway Paris (fr-par) — HDS-certified, RGPD-compliant.
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "fr-par"
    s3_endpoint: str = "https://s3.fr-par.scw.cloud"  # Scaleway Paris default
    s3_recordings_bucket: str = "optibot-recordings"
    recording_retention_days: int = 180  # CNIL guidance: 6 months
    max_llm_tokens: int = 160
    context_budget_tokens: int = 6000

    # ── Hold Detection ──────────────────────────────────
    hold_timeout_sec: float = 1200.0  # 20 min — MGEN holds avg 15 min
    hold_ambiguous_window_sec: float = 8.0
    hold_ambiguous_threshold: int = 2
    hold_min_return_words: int = 4  # weak hints (voila/alors) need >= N words

    # ── AMD (Answering Machine Detection) ───────────────
    amd_detection_timeout_sec: float = 30.0
    amd_speech_threshold_ms: float = 2400.0
    amd_speech_end_threshold_ms: float = 1200.0
    amd_silence_timeout_ms: float = 5000.0
    amd_human_speech_max_ms: float = 2000.0  # French greetings up to 2s

    # ── Keyterm Builder ─────────────────────────────────
    max_keyterms: int = 100
    deepgram_max_keyterm_tokens: int = 500

    # ── Turn Handling & Interruption ────────────────────
    endpointing_min_delay_sec: float = 0.5  # Raised from 0.0 — prevents double-trigger on split STT segments
    endpointing_max_delay_sec: float = 3.0
    interruption_false_timeout_sec: float = 1.5
    interruption_min_words: int = 3  # Raised from 2 — reduces false interrupts for French filler words
    min_consecutive_speech_delay_sec: float = 0.3  # natural pacing
    audio_sample_rate_hz: int = 24000  # higher quality for SIP transcoding

    # ── Call Control ────────────────────────────────────
    max_call_duration_sec: int = 600  # 10 min hard cap
    max_question_retries: int = 2
    silence_keepalive_sec: float = 30.0  # "je suis toujours en ligne" after Ns
    max_tool_steps: int = 8  # default 3 too low for 15+ tools
    cartesia_ws_timeout_warning_sec: float = 60.0  # Cartesia WS dies at ~60s

    # ── Webhooks ─────────────────────────────────────
    webhook_url: str = ""  # POST call outcomes here (empty = disabled)
    webhook_timeout_sec: float = 10.0

    # ── Hosting ──────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    log_level: str = "info"

    @field_validator("debug", mode="before")
    @classmethod
    def coerce_debug(cls, value):
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production"}:
                return False
            if lowered in {"debug", "dev", "development"}:
                return True
        return value
