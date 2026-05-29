"""Remote development / staging environment settings."""

import os

from .base import *  # noqa: F401, F403

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
]

# Use console email backend in development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Trust X-Forwarded-Proto from the gateway (nginx, ALB)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Dev startup validation
if not os.getenv("POSTGRES_DB") or not os.getenv("POSTGRES_HOST"):
    raise ValueError(
        "Database configuration (POSTGRES_DB, POSTGRES_HOST) must be set in dev environment"
    )

if not ALLOWED_HOSTS:
    raise ValueError("ALLOWED_HOSTS must be set in dev environment")

# Key validation — dev is a live EC2 deployment, so keys must be explicit
if not os.getenv("JWT_SIGNING_KEY"):
    raise ValueError(
        "JWT_SIGNING_KEY must be explicitly set in dev environment. "
        "Falling back to SECRET_KEY risks JWT forgery on key rotation."
    )

if not os.getenv("FIELD_ENCRYPTION_KEY"):
    raise ValueError(
        "FIELD_ENCRYPTION_KEY must be explicitly set in dev environment. "
        "Falling back to SECRET_KEY risks data corruption on key rotation."
    )
