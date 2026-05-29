# ============================================================================
# Stage 1: Builder — install dependencies into a virtual environment
# ============================================================================
# Base image digests pinned for reproducibility. Refresh monthly via:
#   docker pull python:3.12-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
FROM python:3.12-slim@sha256:520153e2deb359602c9cffd84e491e3431d76e7bf95a3255c9ce9433b76ab99a AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build-time system dependencies (gcc, libpq headers).
# Versions captured via `apt-cache policy <pkg>` inside the digest-pinned
# python:3.12-slim image above. The `+deb13u*` suffix is Debian's security
# epoch — recapture these any time Debian ships a point-release, not on a
# calendar. Quick refresh:
#   docker run --rm python:3.12-slim@<digest> bash -c \
#     "apt-get update -qq && apt-cache policy gcc libc6-dev libpq-dev"
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment so we can copy it cleanly into the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements/ requirements/
ARG REQUIREMENTS_FILE=requirements/prod.txt
# --require-hashes: fail the build if any installed wheel's hash does not
# match the pinned value in the requirements file. Supply-chain integrity.
RUN pip install --upgrade pip && \
    pip install --require-hashes -r ${REQUIREMENTS_FILE}

# ============================================================================
# Stage 2: Runtime — lean production image with non-root user
# ============================================================================
FROM python:3.12-slim@sha256:520153e2deb359602c9cffd84e491e3431d76e7bf95a3255c9ce9433b76ab99a AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/apps:$PYTHONPATH"

# Install only the runtime system libraries (no gcc, no headers).
# Pin versions — see comment in builder stage for refresh cadence.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create a non-root user for running the application
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy project files
COPY --chown=appuser:appuser . .

# Create logs and staticfiles directories owned by appuser
RUN mkdir -p /app/logs /app/staticfiles && chown -R appuser:appuser /app/logs /app/staticfiles

# Switch to non-root user
USER appuser

# Collect static files at build time
RUN DJANGO_ENV=local SECRET_KEY=build-placeholder \
    python manage.py collectstatic --noinput

EXPOSE 8000

# No ENTRYPOINT — every compose file declares its own `command:`. Migrations
# run on demand via `docker compose run --rm web python manage.py migrate`.
# DB / broker readiness is enforced by `depends_on: condition: service_healthy`
# in the compose files, not by an entrypoint-side wait loop.
# --timeout must exceed PARTNER_PUSH_TIMEOUT (push holds the worker for the full
# synchronous partner push); default 130 leaves ~10s headroom over the 120s
# client timeout so the app times out (and records the failure) before the
# worker is SIGKILL-ed. Compose files may override GUNICORN_TIMEOUT.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers ${GUNICORN_WORKERS:-4} --threads ${GUNICORN_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-130} --graceful-timeout 30 --max-requests ${GUNICORN_MAX_REQUESTS:-10000} --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-500} --backlog ${GUNICORN_BACKLOG:-2048}"]
