"""Structured JSON logging with PII scrubbing.

Microsoft pattern: structlog + OpenTelemetry context propagation.
All phone numbers, NIR, and sensitive IDs are masked before output.
"""
from __future__ import annotations

import logging
import sys

import structlog

from app.observability.telemetry import scrub_pii


def _pii_scrub_processor(logger, method_name, event_dict):
    """Structlog processor that scrubs PII from all string values."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = scrub_pii(value)
    return event_dict


def init_logging(level: str = "info", json_output: bool = True) -> None:
    """Initialize structured logging. Call once at startup."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _pii_scrub_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
