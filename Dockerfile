# ── Builder stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# System dependency for python-magic
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app.py config.py storage.py ./

# Non-root user — UID 1001 must match the token file owner on the host when using local storage
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid 1001 --no-create-home appuser \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Worker count: set WEB_CONCURRENCY env var to override (default: 4)
CMD gunicorn app:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY:-4} \
    --bind 0.0.0.0:5000 \
    --timeout 60 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
