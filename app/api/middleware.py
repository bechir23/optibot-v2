"""API middleware — auth, rate limiting, request logging, security headers."""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import Settings
from app.observability.telemetry import scrub_pii

logger = logging.getLogger(__name__)
settings = Settings()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with latency, scrub PII from paths."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        latency_ms = (time.monotonic() - start) * 1000
        path = scrub_pii(str(request.url.path))
        logger.info(
            "HTTP %s %s %d %.0fms",
            request.method, path, response.status_code, latency_ms,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses (OWASP best practices)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter per tenant for /api/call endpoint.

    Uses a sliding window counter. Not distributed — for single-instance use.
    For multi-instance, use Redis-based rate limiting.
    """

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/api/call" or request.method != "POST":
            return await call_next(request)

        tenant = request.headers.get("X-Tenant-ID", request.client.host if request.client else "unknown")
        now = time.monotonic()

        # Clean old entries
        window_start = now - self._window
        self._requests[tenant] = [t for t in self._requests[tenant] if t > window_start]

        if len(self._requests[tenant]) >= self._max:
            logger.warning("Rate limit exceeded for tenant %s", tenant)
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(self._window)},
            )

        self._requests[tenant].append(now)
        return await call_next(request)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from request and set in context for downstream use."""

    async def dispatch(self, request: Request, call_next):
        tenant_id = request.headers.get("X-Tenant-ID", "")
        if not tenant_id and request.method == "POST":
            try:
                body = await request.json()
                tenant_id = body.get("tenant_id", "")
            except Exception:
                pass
        request.state.tenant_id = tenant_id
        return await call_next(request)
