"""OpenTelemetry initialization — Microsoft dual-layer pattern.

Layer 1: structlog for structured JSON logs with PII scrubbing.
Layer 2: OpenTelemetry for distributed traces + Prometheus metrics.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry, generate_latest

if TYPE_CHECKING:
    pass

# PII patterns for log scrubbing
_PII_PATTERNS = [
    (re.compile(r"\+33\d{9}"), "+33***XXXX"),          # French phone
    (re.compile(r"\+\d{10,15}"), "+XX***XXXX"),         # International phone
    (re.compile(r"\b[12]\d{2}\d{2}\d{2}\w{5}\d{3}\b"), "***NIR***"),  # NIR (sécu sociale)
    (re.compile(r"\b\d{13,15}\b"), "***ID***"),          # Long numeric IDs
]

_tracer: trace.Tracer | None = None
_meter: metrics.Meter | None = None
_registry = CollectorRegistry()


def scrub_pii(text: str) -> str:
    """Remove PII from log messages. Phone numbers, NIR, long IDs."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def init_telemetry(service_name: str = "optibot-v2", otlp_endpoint: str = "http://localhost:4317") -> None:
    """Initialize OpenTelemetry tracing + metrics. Call once at startup."""
    global _tracer, _meter

    resource = Resource.create({"service.name": service_name, "service.version": "0.1.0"})

    # Tracing → Jaeger via OTLP
    tracer_provider = TracerProvider(resource=resource)
    try:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    except Exception:
        pass  # Jaeger not available — traces discarded silently
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer(service_name)

    # Metrics → Prometheus
    try:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        reader = PrometheusMetricReader()
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    except ImportError:
        meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(service_name)


def get_tracer() -> trace.Tracer:
    """Get the global tracer. Returns NoOp tracer if not initialized."""
    return _tracer or trace.get_tracer("optibot-v2")


def get_meter() -> metrics.Meter:
    """Get the global meter. Returns NoOp meter if not initialized."""
    return _meter or metrics.get_meter("optibot-v2")


def get_prometheus_metrics() -> bytes:
    """Generate Prometheus metrics output for /metrics endpoint."""
    return generate_latest(_registry)
