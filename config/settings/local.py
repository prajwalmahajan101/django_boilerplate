"""Local development settings (Docker Compose / bare-metal)."""

import os

from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]

# Use console email backend in local development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Override broker/backend for docker-compose networking
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "django-db")

# Disable throttling for local dev
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
}

# Valkey cache for docker-compose
CACHES = {
    "default": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": os.getenv("VALKEY_CACHE_URL", "valkey://valkey:6379/2"),
        "OPTIONS": {},
    },
    "rate_limit": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": os.getenv("VALKEY_RATE_LIMIT_URL", "valkey://valkey:6379/3"),
        "OPTIONS": {},
        "KEY_PREFIX": "ratelimit",
        "TIMEOUT": 3600,
    },
}
