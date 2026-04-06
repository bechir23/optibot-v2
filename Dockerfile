# ── Stage 1: Build dependencies ────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ───────────────────────────────────
FROM python:3.12-slim

RUN useradd -m -s /bin/bash optibot && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY app/ /app/app/
COPY data/ /app/data/

WORKDIR /app
RUN mkdir -p /app/logs && chown -R optibot:optibot /app

USER optibot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# LiveKit Cloud: runs the agent worker (connects via WebSocket, no inbound ports needed)
# Local docker-compose overrides CMD for api/worker separation
CMD ["python", "-m", "app.main", "start"]
