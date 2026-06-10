"""UAT environment settings.

Sits between dev (loose) and prod (strict): TLS enforcement, short HSTS
so cert/DNS mistakes recover within the hour, explicit fail-fast checks
on critical env vars.
"""

import os

from .base import *
from .base import _env_int  # underscore-prefixed names aren't pulled in by `*`

DEBUG = False

ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# HSTS matches prod posture in UAT so we exercise the preload path before
# production deploys. INCLUDE_SUBDOMAINS + PRELOAD are irreversible at the
# browser level for the SECONDS window, but at one hour we still have a
# recovery path for a bad cert / DNS swap. See docs/configuration.md.
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Trust X-Forwarded-Proto from the gateway nginx in front of gunicorn.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --------------------------------------------------------------------------
# Cache (Valkey — also serves rate limit, circuit breaker, Celery broker)
# --------------------------------------------------------------------------
_valkey_url = os.getenv("VALKEY_CACHE_URL")
if not _valkey_url:
    raise ValueError(
        "VALKEY_CACHE_URL must be set in UAT environment. "
        "Valkey is required for cache, rate limiting, circuit breaker, and Celery broker."
    )

CACHES = {
    "default": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": _valkey_url,
        "OPTIONS": {
            "max_connections": 25,
            "retry_on_timeout": True,
        },
        "KEY_PREFIX": "app",
        "TIMEOUT": 300,
    },
    "rate_limit": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": os.getenv("VALKEY_RATE_LIMIT_URL", _valkey_url),
        "OPTIONS": {
            "max_connections": 20,
        },
        "KEY_PREFIX": "ratelimit",
        "TIMEOUT": 3600,
    },
}

# --------------------------------------------------------------------------
# Celery — broker on Valkey DB 2, results in Django DB. No tasks dispatched
# in UAT today; worker/beat run for parity and to catch .delay() regressions.
# --------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_WORKER_CONCURRENCY = _env_int("CELERY_WORKER_CONCURRENCY", "2")

if not CELERY_BROKER_URL:
    raise ValueError("CELERY_BROKER_URL must be set in UAT environment")
if not CELERY_RESULT_BACKEND:
    raise ValueError("CELERY_RESULT_BACKEND must be set in UAT environment")

# --------------------------------------------------------------------------
# Startup validation
# --------------------------------------------------------------------------
if not ALLOWED_HOSTS:
    raise ValueError("ALLOWED_HOSTS must be set in UAT environment")

if not os.getenv("POSTGRES_DB") or not os.getenv("POSTGRES_HOST"):
    raise ValueError(
        "Database configuration (POSTGRES_DB, POSTGRES_HOST) must be set in UAT — "
        "POSTGRES_HOST should point at the RDS endpoint."
    )

if not os.getenv("JWT_SIGNING_KEY"):
    raise ValueError(
        "JWT_SIGNING_KEY must be explicitly set in UAT. "
        "Falling back to SECRET_KEY risks JWT forgery on key rotation."
    )

if not os.getenv("FIELD_ENCRYPTION_KEY"):
    raise ValueError(
        "FIELD_ENCRYPTION_KEY must be explicitly set in UAT. "
        "Falling back to SECRET_KEY risks data corruption on key rotation."
    )

# Reject wildcard CORS in UAT — origins must be explicit.
if globals().get("CORS_ALLOW_ALL_ORIGINS", False):
    raise ValueError(
        "CORS_ALLOW_ALL_ORIGINS must not be True in UAT. "
        "Set CORS_ALLOWED_ORIGINS to specific origins (comma-separated)."
    )
