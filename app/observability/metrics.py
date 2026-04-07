"""Prometheus metrics helpers for OptiBot runtime.

This module keeps the canonical metric catalog (dot notation) and maps it to
Prometheus-safe names so we do not lose metric intent while still exporting
valid metrics.
"""
from __future__ import annotations

import logging
from enum import StrEnum

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)


class MetricName(StrEnum):
    """Canonical metric names (keep these stable for planning and coverage)."""

    # Latency histograms
    CALL_DURATION = "call.duration.seconds"
    STT_LATENCY = "call.stt.latency.ms"
    LLM_LATENCY = "call.llm.latency.ms"
    TTS_LATENCY = "call.tts.first_audio.ms"
    TTS_FULL_LATENCY = "call.tts.full.ms"
    IVR_LATENCY = "call.ivr.decision.ms"
    RAG_LATENCY = "call.rag.retrieve.ms"
    TOOL_LATENCY = "call.tool.execute.ms"
    INTENT_LATENCY = "call.intent.classify.ms"

    # Counters
    CALLS_TOTAL = "calls.total"
    CALLS_COMPLETED = "calls.completed"
    CALLS_FAILED = "calls.failed"
    IVR_DTMF_SENT = "call.ivr.dtmf.sent"
    IVR_STUCK = "call.ivr.stuck"
    LLM_FALLBACK = "call.llm.fallback.count"
    JSON_REPAIR = "call.json.repair.count"
    CACHE_HIT = "cache.hits"
    CACHE_MISS = "cache.misses"
    AEC_DROPPED = "call.aec.dropped"
    HOLD_DETECTED = "call.hold.detected"
    TOOL_CALLED = "call.tool.called"

    # Gauges
    CALLS_ACTIVE = "calls.active"


_PROM_NAME = {
    MetricName.CALL_DURATION: "optibot_call_duration_seconds",
    MetricName.STT_LATENCY: "optibot_call_stt_latency_ms",
    MetricName.LLM_LATENCY: "optibot_call_llm_latency_ms",
    MetricName.TTS_LATENCY: "optibot_call_tts_first_audio_ms",
    MetricName.TTS_FULL_LATENCY: "optibot_call_tts_full_ms",
    MetricName.IVR_LATENCY: "optibot_call_ivr_decision_ms",
    MetricName.RAG_LATENCY: "optibot_call_rag_retrieve_ms",
    MetricName.TOOL_LATENCY: "optibot_call_tool_execute_ms",
    MetricName.INTENT_LATENCY: "optibot_call_intent_classify_ms",
    MetricName.CALLS_TOTAL: "optibot_calls_total",
    MetricName.CALLS_COMPLETED: "optibot_calls_completed_total",
    MetricName.CALLS_FAILED: "optibot_calls_failed_total",
    MetricName.IVR_DTMF_SENT: "optibot_call_ivr_dtmf_sent_total",
    MetricName.IVR_STUCK: "optibot_call_ivr_stuck_total",
    MetricName.LLM_FALLBACK: "optibot_call_llm_fallback_total",
    MetricName.JSON_REPAIR: "optibot_call_json_repair_total",
    MetricName.CACHE_HIT: "optibot_cache_hits_total",
    MetricName.CACHE_MISS: "optibot_cache_misses_total",
    MetricName.AEC_DROPPED: "optibot_call_aec_dropped_total",
    MetricName.HOLD_DETECTED: "optibot_hold_events_total",
    MetricName.TOOL_CALLED: "optibot_tool_calls_total",
    MetricName.CALLS_ACTIVE: "optibot_calls_active",
}


def _name(metric: MetricName) -> str:
    return _PROM_NAME[metric]


CALL_DURATION_SECONDS = Histogram(
    _name(MetricName.CALL_DURATION),
    "End-to-end call duration in seconds",
    buckets=(5, 10, 20, 30, 60, 120, 300, 600, 1200),
)

STT_LATENCY_MS = Histogram(
    _name(MetricName.STT_LATENCY),
    "STT latency in milliseconds",
    buckets=(10, 25, 50, 100, 200, 400, 800, 1500, 3000, 5000, 10000),
)

LLM_LATENCY_MS = Histogram(
    _name(MetricName.LLM_LATENCY),
    "LLM latency in milliseconds",
    buckets=(25, 50, 100, 200, 400, 800, 1500, 3000, 5000, 10000, 20000),
)

TTS_FIRST_AUDIO_LATENCY_MS = Histogram(
    _name(MetricName.TTS_LATENCY),
    "TTS first-audio latency in milliseconds",
    buckets=(25, 50, 100, 200, 400, 800, 1500, 3000, 5000),
)

TTS_FULL_LATENCY_MS = Histogram(
    _name(MetricName.TTS_FULL_LATENCY),
    "TTS full synthesis latency in milliseconds",
    buckets=(50, 100, 200, 400, 800, 1500, 3000, 5000, 10000, 20000),
)

IVR_DECISION_LATENCY_MS = Histogram(
    _name(MetricName.IVR_LATENCY),
    "IVR decision latency in milliseconds",
    buckets=(10, 25, 50, 100, 200, 400, 800, 1500, 3000),
)

RAG_RETRIEVE_LATENCY_MS = Histogram(
    _name(MetricName.RAG_LATENCY),
    "RAG retrieval latency in milliseconds",
    buckets=(5, 10, 25, 50, 100, 200, 400, 800, 1500, 3000, 5000),
)

TOOL_EXECUTE_LATENCY_MS = Histogram(
    _name(MetricName.TOOL_LATENCY),
    "Tool execution latency in milliseconds",
    buckets=(1, 2, 5, 10, 25, 50, 100, 200, 400, 800, 1500),
)

INTENT_CLASSIFY_LATENCY_MS = Histogram(
    _name(MetricName.INTENT_LATENCY),
    "Intent classification latency in milliseconds",
    buckets=(10, 25, 50, 100, 200, 400, 800, 1500, 3000),
)

# Backward compatibility for existing dashboards and queries.
RAG_RETRIEVE_LATENCY_SECONDS_LEGACY = Histogram(
    "optibot_rag_retrieve_latency_seconds",
    "RAG retrieval latency in seconds (legacy)",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5),
)

CALLS_TOTAL = Counter(
    _name(MetricName.CALLS_TOTAL),
    "Total calls started",
    ["tenant_id", "mutuelle"],
)

CALLS_COMPLETED = Counter(
    _name(MetricName.CALLS_COMPLETED),
    "Total calls completed",
    ["tenant_id", "mutuelle", "outcome"],
)

CALLS_FAILED = Counter(
    _name(MetricName.CALLS_FAILED),
    "Total calls failed",
    ["tenant_id", "mutuelle", "reason"],
)

IVR_DTMF_SENT = Counter(
    _name(MetricName.IVR_DTMF_SENT),
    "DTMF digits sent by the agent",
    ["tenant_id", "mutuelle", "digit"],
)

IVR_STUCK = Counter(
    _name(MetricName.IVR_STUCK),
    "IVR stuck incidents",
    ["tenant_id", "mutuelle"],
)

LLM_FALLBACK_COUNT = Counter(
    _name(MetricName.LLM_FALLBACK),
    "LLM fallback invocations",
    ["tenant_id", "provider"],
)

JSON_REPAIR_COUNT = Counter(
    _name(MetricName.JSON_REPAIR),
    "json-repair corrections applied",
    ["tenant_id"],
)

CACHE_HITS = Counter(
    _name(MetricName.CACHE_HIT),
    "Cache hits by tier",
    ["tier"],
)

CACHE_MISSES = Counter(
    _name(MetricName.CACHE_MISS),
    "Cache misses by tier",
    ["tier"],
)

AEC_DROPPED = Counter(
    _name(MetricName.AEC_DROPPED),
    "Audio frames dropped by AEC or noise suppression",
    ["tenant_id", "reason"],
)

HOLD_EVENTS = Counter(
    _name(MetricName.HOLD_DETECTED),
    "Hold lifecycle events",
    ["tenant_id", "event"],
)

TOOL_CALLS = Counter(
    _name(MetricName.TOOL_CALLED),
    "Tools invoked by the voice agent",
    ["tenant_id", "tool_name"],
)

CALLS_ACTIVE = Gauge(
    _name(MetricName.CALLS_ACTIVE),
    "Active calls currently in progress",
    ["tenant_id"],
)

# ── Config registry metrics ──────────────────────────────────────
CONFIG_RELOAD_TOTAL = Counter(
    "optibot_config_reload_total",
    "Config registry reload attempts",
    ["status"],  # success, failure
)

CONFIG_ACTIVE_VERSION = Gauge(
    "optibot_config_active_version",
    "Current active config version",
)

CONFIG_RELOAD_DURATION_MS = Histogram(
    "optibot_config_reload_duration_ms",
    "Config reload duration in ms",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2000),
)


def record_config_reload(success: bool, duration_ms: float, version: int) -> None:
    CONFIG_RELOAD_TOTAL.labels("success" if success else "failure").inc()
    CONFIG_RELOAD_DURATION_MS.observe(duration_ms)
    if success:
        CONFIG_ACTIVE_VERSION.set(version)


def _safe_label(value: str | None, fallback: str = "unknown") -> str:
    if not value:
        return fallback
    cleaned = str(value).strip().lower().replace(" ", "_")
    return cleaned[:64] or fallback


def _observe_ms(histogram: Histogram, duration_ms: float) -> None:
    if duration_ms > 0:
        histogram.observe(duration_ms)


def record_call_started(tenant_id: str, mutuelle: str) -> None:
    tenant = _safe_label(tenant_id)
    payer = _safe_label(mutuelle)
    CALLS_TOTAL.labels(tenant, payer).inc()
    CALLS_ACTIVE.labels(tenant).inc()


def record_call_completed(tenant_id: str, mutuelle: str, outcome: str, duration_seconds: float) -> None:
    tenant = _safe_label(tenant_id)
    payer = _safe_label(mutuelle)
    result = _safe_label(outcome)
    CALLS_COMPLETED.labels(tenant, payer, result).inc()
    CALLS_ACTIVE.labels(tenant).dec()
    if duration_seconds > 0:
        CALL_DURATION_SECONDS.observe(duration_seconds)


def record_call_failed(tenant_id: str, mutuelle: str, reason: str) -> None:
    tenant = _safe_label(tenant_id)
    payer = _safe_label(mutuelle)
    why = _safe_label(reason)
    CALLS_FAILED.labels(tenant, payer, why).inc()
    CALLS_ACTIVE.labels(tenant).dec()


def record_hold_event(
    tenant_id: str,
    event: str,
    *,
    call_id: str = "",
    mutuelle: str = "",
    reason: str = "",
    triggering_phrase: str = "",
    duration: float = 0.0,
) -> None:
    """Record a hold lifecycle event with structured context for debugging.

    H3 FIX: prior version only recorded (tenant, event) which made it
    impossible to debug a false positive in production. Now logs the
    triggering phrase, hold reason, and duration so operators can trace
    why a specific call was suppressed.

    triggering_phrase is truncated to 80 chars (PII-safe — no NIR/dossier).
    """
    tenant = _safe_label(tenant_id)
    HOLD_EVENTS.labels(tenant, _safe_label(event)).inc()
    if call_id or mutuelle or reason or triggering_phrase:
        logger.info(
            "hold_event event=%s call_id=%s mutuelle=%s reason=%s duration=%.1f triggering_phrase=%r",
            event,
            call_id or "-",
            mutuelle or "-",
            reason or "-",
            duration,
            (triggering_phrase or "")[:80],
        )


def record_tool_called(tenant_id: str, tool_name: str) -> None:
    tenant = _safe_label(tenant_id)
    TOOL_CALLS.labels(tenant, _safe_label(tool_name)).inc()


def record_ivr_dtmf_sent(tenant_id: str, mutuelle: str, digit: str) -> None:
    IVR_DTMF_SENT.labels(
        _safe_label(tenant_id),
        _safe_label(mutuelle),
        _safe_label(digit, fallback="none"),
    ).inc()


def record_ivr_stuck(tenant_id: str, mutuelle: str) -> None:
    IVR_STUCK.labels(_safe_label(tenant_id), _safe_label(mutuelle)).inc()


def record_llm_fallback(tenant_id: str, provider: str) -> None:
    LLM_FALLBACK_COUNT.labels(_safe_label(tenant_id), _safe_label(provider)).inc()


def record_json_repair(tenant_id: str) -> None:
    JSON_REPAIR_COUNT.labels(_safe_label(tenant_id)).inc()


def record_cache_hit(tier: str) -> None:
    CACHE_HITS.labels(_safe_label(tier)).inc()


def record_cache_miss(tier: str) -> None:
    CACHE_MISSES.labels(_safe_label(tier)).inc()


def record_aec_dropped(tenant_id: str, reason: str) -> None:
    AEC_DROPPED.labels(_safe_label(tenant_id), _safe_label(reason)).inc()


def observe_stt_latency_ms(duration_ms: float) -> None:
    _observe_ms(STT_LATENCY_MS, duration_ms)


def observe_llm_latency_ms(duration_ms: float) -> None:
    _observe_ms(LLM_LATENCY_MS, duration_ms)


def observe_tts_first_audio_latency_ms(duration_ms: float) -> None:
    _observe_ms(TTS_FIRST_AUDIO_LATENCY_MS, duration_ms)


def observe_tts_full_latency_ms(duration_ms: float) -> None:
    _observe_ms(TTS_FULL_LATENCY_MS, duration_ms)


def observe_ivr_latency_ms(duration_ms: float) -> None:
    _observe_ms(IVR_DECISION_LATENCY_MS, duration_ms)


def observe_rag_latency_ms(duration_ms: float) -> None:
    _observe_ms(RAG_RETRIEVE_LATENCY_MS, duration_ms)


def observe_tool_latency_ms(duration_ms: float) -> None:
    _observe_ms(TOOL_EXECUTE_LATENCY_MS, duration_ms)


def observe_intent_latency_ms(duration_ms: float) -> None:
    _observe_ms(INTENT_CLASSIFY_LATENCY_MS, duration_ms)


def observe_rag_latency(duration_seconds: float) -> None:
    """Compatibility helper used by existing code paths."""
    if duration_seconds > 0:
        RAG_RETRIEVE_LATENCY_SECONDS_LEGACY.observe(duration_seconds)
        observe_rag_latency_ms(duration_seconds * 1000.0)
