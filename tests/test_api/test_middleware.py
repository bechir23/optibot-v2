"""Tests for API middleware — rate limiting with Redis fallback."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import RateLimitMiddleware, TenantContextMiddleware


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    async def incr(self, key: str, ttl: int | None = None) -> int | None:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def _build_test_app(max_requests: int = 2):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, max_requests=max_requests, window_seconds=60)
    app.add_middleware(TenantContextMiddleware)

    @app.post("/api/call")
    async def create_call():
        return {"status": "ok"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def test_rate_limit_blocks_after_max(monkeypatch):
    """Rate limiter blocks requests after max_requests."""
    from app.main import app_state

    fake_redis = FakeRedis()
    monkeypatch.setattr(app_state, "redis", fake_redis)

    client = TestClient(_build_test_app(max_requests=2))

    r1 = client.post("/api/call", json={"tenant_id": "t1"})
    r2 = client.post("/api/call", json={"tenant_id": "t1"})
    r3 = client.post("/api/call", json={"tenant_id": "t1"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert any(k.startswith("ratelimit:t1:") for k in fake_redis.counts)


def test_non_api_call_routes_bypass_rate_limit(monkeypatch):
    """Non /api/call routes are not rate limited."""
    from app.main import app_state
    monkeypatch.setattr(app_state, "redis", None)

    client = TestClient(_build_test_app(max_requests=1))

    r1 = client.get("/health")
    r2 = client.get("/health")

    assert r1.status_code == 200
    assert r2.status_code == 200


def test_fallback_to_inmemory_when_redis_unavailable(monkeypatch):
    """Falls back to in-memory rate limiting when Redis is None."""
    from app.main import app_state
    monkeypatch.setattr(app_state, "redis", None)

    client = TestClient(_build_test_app(max_requests=1))

    r1 = client.post("/api/call", json={"tenant_id": "t2"})
    r2 = client.post("/api/call", json={"tenant_id": "t2"})

    assert r1.status_code == 200
    assert r2.status_code == 429
