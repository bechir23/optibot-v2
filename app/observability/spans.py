"""Named spans for distributed tracing — Microsoft call-center-ai pattern.

Every pipeline stage gets a named span with call_sid, tenant_id, mutuelle, phase.
Exported to Jaeger via OTLP.
"""
from enum import StrEnum


class SpanName(StrEnum):
    """Span names matching Microsoft's SpanMeterEnum pattern."""

    # Call lifecycle
    CALL_LIFECYCLE = "call.lifecycle"
    CALL_SETUP = "call.setup"
    CALL_TEARDOWN = "call.teardown"

    # IVR navigation
    CALL_IVR_NAVIGATE = "call.ivr.navigate"
    CALL_IVR_DTMF = "call.ivr.dtmf"
    CALL_IVR_DETECT_HUMAN = "call.ivr.detect_human"

    # Audio pipeline
    CALL_STT = "call.stt.transcribe"
    CALL_STT_CORRECTION = "call.stt.correction"
    CALL_TTS = "call.tts.synthesize"
    CALL_AEC = "call.aec.process"

    # LLM + tools
    CALL_LLM = "call.llm.generate"
    CALL_LLM_FALLBACK = "call.llm.fallback"
    CALL_TOOL_EXECUTE = "call.tool.execute"
    CALL_TOOL_EXTRACT = "call.tool.extract"

    # RAG
    CALL_RAG_RETRIEVE = "call.rag.retrieve"
    CALL_RAG_EMBED = "call.rag.embed"

    # Cache
    CALL_CACHE_GET = "call.cache.get"
    CALL_CACHE_SET = "call.cache.set"

    # Hold detection
    CALL_HOLD_DETECT = "call.hold.detect"
    CALL_HOLD_END = "call.hold.end"


class SpanAttribute(StrEnum):
    """Standard attributes attached to every span."""

    CALL_SID = "call.sid"
    TENANT_ID = "tenant.id"
    MUTUELLE = "call.mutuelle"
    PHASE = "call.phase"
    TOOL_NAME = "tool.name"
    LLM_MODEL = "llm.model"
    LLM_TOKENS = "llm.tokens"
    CACHE_TIER = "cache.tier"
    CACHE_HIT = "cache.hit"
