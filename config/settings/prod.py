"""Production environment settings."""

import os

from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
]

# --------------------------------------------------------------------------
# Security hardening
# --------------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Trust X-Forwarded-Proto from the gateway (nginx, ALB)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --------------------------------------------------------------------------
# Production cache (Valkey with connection pooling)
# --------------------------------------------------------------------------
_valkey_url = os.getenv("VALKEY_CACHE_URL")
if not _valkey_url:
    raise ValueError(
        "VALKEY_CACHE_URL must be set in production environment. "
        "Valkey is required for caching, rate limiting, and task management."
    )

CACHES = {
    "default": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": _valkey_url,
        "OPTIONS": {
            "max_connections": 25,
            "retry_on_timeout": True,
        },
        # Cache key namespace. Defaulting to "app" so a fresh adopter
        # never silently inherits the donor project's prefix. Set
        # CACHE_KEY_PREFIX in deploy env to namespace per service —
        # required if multiple services share one Valkey instance.
        "KEY_PREFIX": os.getenv("CACHE_KEY_PREFIX", "app"),
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
# Celery production overrides (no defaults — must be set)
# --------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_WORKER_CONCURRENCY = _env_int("CELERY_WORKER_CONCURRENCY", "4")  # noqa: F405

if not CELERY_BROKER_URL:
    raise ValueError("CELERY_BROKER_URL must be set in production environment")
if not CELERY_RESULT_BACKEND:
    raise ValueError("CELERY_RESULT_BACKEND must be set in production environment")

# --------------------------------------------------------------------------
# Production validation
# --------------------------------------------------------------------------
if not ALLOWED_HOSTS:
    raise ValueError("ALLOWED_HOSTS must be set in production environment")

if not os.getenv("POSTGRES_DB") or not os.getenv("POSTGRES_HOST"):
    raise ValueError(
        "Database configuration (POSTGRES_DB, POSTGRES_HOST) must be set in production"
    )

_db_password = os.getenv("POSTGRES_PASSWORD", "")
if not _db_password or _db_password == "postgres":
    raise ValueError(
        "POSTGRES_PASSWORD must be set to a non-default value in production"
    )

# Reject wildcard CORS in production
if globals().get("CORS_ALLOW_ALL_ORIGINS", False):
    raise ValueError(
        "CORS_ALLOW_ALL_ORIGINS must not be True in production. "
        "Set CORS_ALLOWED_ORIGINS to specific origins (comma-separated)."
    )

if not os.getenv("JWT_SIGNING_KEY"):
    raise ValueError(
        "JWT_SIGNING_KEY must be explicitly set in production. "
        "Falling back to SECRET_KEY risks JWT forgery on key rotation."
    )

if not os.getenv("FIELD_ENCRYPTION_KEY"):
    raise ValueError(
        "FIELD_ENCRYPTION_KEY must be explicitly set in production. "
        "Falling back to SECRET_KEY risks data corruption on key rotation."
    )
