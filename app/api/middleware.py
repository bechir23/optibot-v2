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
    """Rate limiter per tenant+IP for /api/call endpoint.

    Tries Redis first (distributed, multi-instance safe).
    Falls back to in-memory sliding window for single-instance use.
    """

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    @staticmethod
    def _scope_key(request: Request) -> str:
        """Scope rate limiting by tenant + client IP to prevent spoofing."""
        tenant = getattr(request.state, "tenant_id", "") or "unknown"
        client_ip = request.client.host if request.client else "unknown"
        return f"{tenant}:{client_ip}"

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/api/call" or request.method != "POST":
            return await call_next(request)

        scope_key = self._scope_key(request)
        now = time.monotonic()

        # Try Redis-backed rate limiting first (distributed)
        try:
            from app.main import app_state
            redis_client = getattr(app_state, "redis", None) if app_state is not None else None
        except Exception:
            redis_client = None

        if redis_client is not None:
            bucket = int(time.time() // self._window)
            redis_key = f"ratelimit:{scope_key}:{bucket}"
            count = await redis_client.incr(redis_key, ttl=self._window + 1)
            if count is not None and count > self._max:
                logger.warning("Rate limit exceeded for scope %s via Redis", scope_key)
                return Response(
                    content='{"detail":"Rate limit exceeded. Try again later."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(self._window)},
                )
            if count is not None:
                return await call_next(request)

        # Fallback: in-memory sliding window
        window_start = now - self._window
        self._requests[scope_key] = [t for t in self._requests[scope_key] if t > window_start]

        if len(self._requests[scope_key]) >= self._max:
            logger.warning("Rate limit exceeded for scope %s", scope_key)
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(self._window)},
            )

        self._requests[scope_key].append(now)
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
