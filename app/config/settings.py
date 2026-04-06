"""Centralized configuration — all env vars, no hardcoded values."""
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
    telnyx_sip_trunk_id: str = ""
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

    # ── Security ─────────────────────────────────────
    api_key: str = ""
    dossier_encryption_key: str = ""

    # ── Feature flags (Microsoft pattern: runtime-tunable) ──
    answer_soft_timeout_sec: float = 4.0
    answer_hard_timeout_sec: float = 15.0
    phone_silence_timeout_sec: float = 20.0
    max_ivr_attempts: int = 5
    max_concurrent_calls: int = 10
    recording_enabled: bool = False
    max_llm_tokens: int = 160
    context_budget_tokens: int = 6000

    # ── Hosting ──────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    log_level: str = "info"
