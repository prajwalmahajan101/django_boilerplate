"""Base settings shared across all environments.

This is a boilerplate base; edit ``INSTALLED_APPS``, the API description
blob, and admin-sidebar links per project.
"""

import os
import re
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from kombu import Queue


def _env_int(name: str, default: str) -> int:
    """Parse an environment variable as int with a clear error on failure."""
    value = os.getenv(name, default)
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ImproperlyConfigured(f"{name}={value!r} is not a valid integer")


def _env_bool(name: str, default: str) -> bool:
    """Parse an environment variable as bool. Accepts true/false/1/0/yes/no."""
    value = os.getenv(name, default).strip().lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off", ""):
        return False
    raise ImproperlyConfigured(f"{name}={value!r} is not a valid boolean")

# config/settings/base.py -> config/settings/ -> config/ -> project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "The SECRET_KEY environment variable is not set. "
        "Set it in your .env file or environment."
    )

# Dedicated key for EncryptedCharField (sensitive credentials at rest).
# Decoupled from SECRET_KEY so that routine SECRET_KEY rotation does not
# silently corrupt encrypted data. Falls back to SECRET_KEY if not set.
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY") or SECRET_KEY

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# --------------------------------------------------------------------------
# Application definition
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    # Unfold admin (must be before django.contrib.admin)
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    # Django built-in
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
    # allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "dj_rest_auth",
    "dj_rest_auth.registration",
    # Project apps
    "core",
    "accounts",
]

AUTH_USER_MODEL = "accounts.User"
SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.security_headers.SecurityHeadersMiddleware",
    "core.middleware.request_id.RequestIDMiddleware",
    "core.middleware.exception_logging.ExceptionLoggingMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.request_logging.RequestLoggingMiddleware",
    "core.middleware.rate_limit_headers.RateLimitHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Database (override in env-specific files if needed)
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "app"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": _env_int("DB_CONN_MAX_AGE", "600"),
        "CONN_HEALTH_CHECKS": True,
    }
}

# --------------------------------------------------------------------------
# Auth password validators
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Internationalization
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
# API is JWT-only; sessions are used only by /admin/ and the allauth Google
# OAuth flow. Moving off the DB backend removes per-request session SELECT/
# UPDATE and scales cleanly under gthread Gunicorn.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# --------------------------------------------------------------------------
# Django REST Framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "core.utils.pagination.StandardPageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    # JWT-only auth for API endpoints. SessionAuthentication is
    # removed to avoid CSRF conflicts for SPA clients that happen to
    # carry a Django session cookie (e.g. admin users hitting the API).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "accounts.authentication.APIKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "core.exceptions.handler.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "core.resilience.throttles.UserTierThrottle",
        "core.resilience.throttles.BurstThrottle",
        "core.resilience.throttles.GlobalThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # `auth_burst` scope is used by AuthEndpointThrottle (5/min anon).
        # Distinct from the existing `auth` scope (20/hour) — the two are
        # complementary: `auth` catches sustained brute force, `auth_burst`
        # catches a fast credential-stuffing burst.
        "auth_burst": "5/min",
    },
    # Number of trusted proxy hops in front of the app. DRF's
    # ``BaseThrottle.get_ident`` reads this to decide how many entries
    # to strip from ``X-Forwarded-For`` before bucketing. Default 0 is
    # safe for local development; behind nginx set ``NUM_PROXIES=1``,
    # behind ALB + nginx set ``NUM_PROXIES=2``. Without this, every
    # anon client behind a proxy shares ``REMOTE_ADDR=<proxy-ip>`` and
    # every anon-IP throttle collapses into a single bucket.
    "NUM_PROXIES": _env_int("NUM_PROXIES", "0"),
}

# --------------------------------------------------------------------------
# DRF Spectacular (OpenAPI schema)
# --------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "Django Boilerplate API",
    "DESCRIPTION": (
        "Project API. Replace this description in `SPECTACULAR_SETTINGS` "
        "in `config/settings/base.py` with one specific to your service.\n\n"
        "## Authentication\n\n"
        "- **Bearer JWT** via `POST /api/auth/login/` (or OAuth provider). "
        "Pass as `Authorization: Bearer <token>`.\n"
        "- **API Key** via `POST /api/accounts/api-keys/`. "
        "Pass as `X-API-Key: <key>`.\n\n"
        "## Response Envelope\n\n"
        "All responses share a common JSON envelope with "
        "`success`, `message`, `data`, `errors`, `request_id`. "
        "Paginated list endpoints wrap items under `data.items` with a "
        "`data.pagination` object.\n"
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/",
    # Declare both auth schemes as global requirements so Swagger UI shows
    # the Authorize button with both options. Individual endpoints that don't
    # require auth (health, readiness) override this via security=[].
    "SECURITY": [{"jwtAuth": []}, {"apiKeyAuth": []}],
    # Tag ordering — Swagger UI / ReDoc render groups in this order rather
    # than alphabetically. Each entry's ``description`` shows up inline at
    # the top of that tag's section.
    "TAGS": [
        {"name": "System", "description": "Health and readiness probes. No auth required."},
        {"name": "Auth", "description": "Login, JWT token refresh, logout, and current-user profile."},
        {"name": "API Keys", "description": "Issue, list, and revoke service-account API keys."},
    ],
}

# --------------------------------------------------------------------------
# CORS Configuration
# --------------------------------------------------------------------------
_cors_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
)
if _cors_origins.strip() == "*":
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOW_CREDENTIALS = False
else:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()]
    CORS_ALLOW_CREDENTIALS = True

# --------------------------------------------------------------------------
# Cache Configuration (dual-cache: default + rate_limit)
# Uses Valkey (Redis-compatible fork) via django-valkey
# --------------------------------------------------------------------------
_valkey_cache_url = os.getenv("VALKEY_CACHE_URL", "valkey://localhost:6379/2")
_valkey_rate_limit_url = os.getenv("VALKEY_RATE_LIMIT_URL", _valkey_cache_url)

CACHES = {
    "default": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": _valkey_cache_url,
        "OPTIONS": {},
    },
    "rate_limit": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": _valkey_rate_limit_url,
        "OPTIONS": {},
        "KEY_PREFIX": "ratelimit",
        "TIMEOUT": 3600,
    },
}

# --------------------------------------------------------------------------
# Proxy header trust
# --------------------------------------------------------------------------
USE_X_FORWARDED_FOR = os.getenv("USE_X_FORWARDED_FOR", "False") == "True"

# --------------------------------------------------------------------------
# SSRF defense — reject outbound URLs that resolve to private/reserved IP space.
# Applied by core.utils.http_client._assert_public_url and partners.models
# field validators. Override to False in tests that use localhost mock servers.
# --------------------------------------------------------------------------
SSRF_BLOCK_PRIVATE_IPS = os.getenv("SSRF_BLOCK_PRIVATE_IPS", "True") == "True"

# --------------------------------------------------------------------------
# Unfold Admin
# --------------------------------------------------------------------------
UNFOLD = {
    "SITE_TITLE": "Django Boilerplate",
    "SITE_HEADER": "Django Boilerplate",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Accounts",
                "items": [
                    {
                        "title": "Users",
                        "icon": "people",
                        "link": "/admin/accounts/user/",
                    },
                    {
                        "title": "Roles",
                        "icon": "shield_person",
                        "link": "/admin/accounts/role/",
                    },
                    {
                        "title": "Permissions",
                        "icon": "lock",
                        "link": "/admin/accounts/permission/",
                    },
                    {
                        "title": "API Keys",
                        "icon": "key",
                        "link": "/admin/accounts/apikey/",
                    },
                ],
            },
            {
                "title": "Celery",
                "items": [
                    {
                        "title": "Task Results",
                        "icon": "task_alt",
                        "link": "/admin/django_celery_results/taskresult/",
                    },
                    {
                        "title": "Periodic Tasks",
                        "icon": "schedule",
                        "link": "/admin/django_celery_beat/periodictask/",
                    },
                ],
            },
        ],
    },
}

# --------------------------------------------------------------------------
# Celery
# --------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "django-db")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_RESULT_EXPIRES = 3600  # 1 hour
CELERY_TIMEZONE = TIME_ZONE

# Task execution
CELERY_TASK_TRACK_STARTED = True
# Time-limits are env-driven so prod / dev / local can pick different bounds
# without a code change. Soft limit raises SoftTimeLimitExceeded so tasks
# can clean up; hard limit SIGKILLs the worker thread.
CELERY_TASK_TIME_LIMIT = _env_int("CELERY_TASK_TIME_LIMIT", "1800")
CELERY_TASK_SOFT_TIME_LIMIT = _env_int("CELERY_TASK_SOFT_TIME_LIMIT", "1500")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = _env_int("CELERY_WORKER_PREFETCH_MULTIPLIER", "1")

# Worker settings
CELERY_WORKER_POOL = "threads"
CELERY_WORKER_CONCURRENCY = _env_int("CELERY_WORKER_CONCURRENCY", "4")

# Monitoring events — toggleable because per-task event emission adds broker
# overhead under high throughput. Default ON (visibility wins in dev / uat);
# recommend OFF in prod once Flower / monitoring is replaced by metrics.
CELERY_WORKER_SEND_TASK_EVENTS = _env_bool("CELERY_SEND_EVENTS", "true")
CELERY_TASK_SEND_SENT_EVENT = _env_bool("CELERY_SEND_EVENTS", "true")

CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_TASK_QUEUES = (
    Queue("high_priority", routing_key="high"),
    Queue("default", routing_key="default"),
    Queue("low_priority", routing_key="low"),
)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_DEFAULT_ROUTING_KEY = "default"

# Domain apps register their task routes here in AppConfig.ready() — leaving
# this empty means every task lands in `default` and the priority queues
# above are declared but unreachable. Example wiring:
#     CELERY_TASK_ROUTES = {
#         "accounts.tasks.send_welcome_email": {"queue": "high_priority"},
#         "reports.tasks.nightly_rollup":       {"queue": "low_priority"},
#     }
# See docs/celery-topology.md for the override convention.
CELERY_TASK_ROUTES = {}

# --------------------------------------------------------------------------
# Log Sanitization (used by core.utils.log_sanitization)
# --------------------------------------------------------------------------
_BASE_MASK_PATTERN = (
    r"password|passwd|secret|token|key|auth|credential|api_key|apikey|"
    r"private|session|cookie|bearer|jwt|access_token|refresh_token"
)
_user_mask_pattern = os.getenv("LOG_MASK_PATTERN", "")
_combined_pattern = (
    f"{_BASE_MASK_PATTERN}|{_user_mask_pattern}" if _user_mask_pattern else _BASE_MASK_PATTERN
)
_sensitive_pattern = re.compile(_combined_pattern, re.IGNORECASE)

LOG_SANITIZATION = {
    "SANITIZE_ENABLED": os.getenv("LOG_SANITIZE_ENABLED", "true").lower() == "true",
    "MAX_STRING_LENGTH": _env_int("LOG_MAX_STRING_LENGTH", "200"),
    "MAX_DICT_KEYS": _env_int("LOG_MAX_DICT_KEYS", "20"),
    "MAX_LIST_ITEMS": _env_int("LOG_MAX_LIST_ITEMS", "10"),
    "SENSITIVE_PATTERN": _sensitive_pattern,
    "MASK_VALUE": "***REDACTED***",
    "EXCLUDED_FIELDS": frozenset(
        os.getenv(
            "LOG_EXCLUDED_FIELDS",
            "password,secret_ref,api_key,private_key,access_token",
        )
        .lower()
        .split(",")
    ),
}

# --------------------------------------------------------------------------
# Rate Limiting (used by core.resilience.throttles)
# --------------------------------------------------------------------------
RATE_LIMIT_CONFIG = {
    "FAIL_OPEN": os.getenv("RATE_LIMIT_FAIL_OPEN", "true").lower() == "true",
    "ENABLE_HEADERS": os.getenv("RATE_LIMIT_ENABLE_HEADERS", "true").lower() == "true",
    "USER_RATES": {
        "anon": os.getenv("RATE_LIMIT_ANON", "100/hour"),
        "user": os.getenv("RATE_LIMIT_USER", "1000/hour"),
        "admin": os.getenv("RATE_LIMIT_ADMIN", "5000/hour"),
    },
    "BURST_RATE": os.getenv("RATE_LIMIT_BURST", "10/second"),
    "GLOBAL_RATE": os.getenv("RATE_LIMIT_GLOBAL", "10000/minute"),
    "ENDPOINT_RATES": {},
}

# --------------------------------------------------------------------------
# Circuit Breaker (used by core.resilience.circuit_breaker.provider)
# --------------------------------------------------------------------------
CIRCUIT_BREAKER_CONFIG = {
    "VALKEY_ALIAS": os.getenv("CIRCUIT_BREAKER_VALKEY_ALIAS", "rate_limit"),
    "KEY_PREFIX": os.getenv("CIRCUIT_BREAKER_KEY_PREFIX", "cb"),
    "FAIL_OPEN": os.getenv("CIRCUIT_BREAKER_FAIL_OPEN", "true").lower() == "true",
}

# --------------------------------------------------------------------------
# Resilience Defaults (used by core.resilience.registry)
# --------------------------------------------------------------------------
RESILIENCE_DEFAULTS = {
    "circuit_breaker": {
        "fail_max": _env_int("RESILIENCE_CB_FAIL_MAX", "5"),
        "reset_timeout": _env_int("RESILIENCE_CB_RESET_TIMEOUT", "30"),
    },
    "retry": {
        "max_attempts": _env_int("RESILIENCE_RETRY_MAX_ATTEMPTS", "3"),
        "wait_min": _env_int("RESILIENCE_RETRY_WAIT_MIN", "1"),
        "wait_max": _env_int("RESILIENCE_RETRY_WAIT_MAX", "10"),
        "retry_on": (
            "core.exceptions.infrastructure.TransientError",
            "core.exceptions.infrastructure.ExternalTimeoutError",
        ),
    },
}

# --------------------------------------------------------------------------
# Authentication Backends
# --------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "accounts.backends.RBACBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# --------------------------------------------------------------------------
# django-allauth (v65+ syntax)
# --------------------------------------------------------------------------
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# Require email verification for email/password signups to prevent
# address squatting. Google OAuth is exempt (SOCIALACCOUNT_EMAIL_VERIFICATION = "none").
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "APP": {
            "client_id": os.getenv("GOOGLE_OAUTH2_CLIENT_ID", ""),
            "secret": os.getenv("GOOGLE_OAUTH2_CLIENT_SECRET", ""),
        },
        "VERIFIED_EMAIL": True,
    }
}

ACCOUNT_ADAPTER = "accounts.adapters.CustomAccountAdapter"
SOCIALACCOUNT_ADAPTER = "accounts.adapters.CustomSocialAccountAdapter"

# Allowed redirect URIs for Google OAuth (defense-in-depth).
# Set via env var as comma-separated list. Empty = skip validation
# (relies on Google's server-side check only).
_redirect_uris = os.getenv("GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS", "")
GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS = [
    u.strip() for u in _redirect_uris.split(",") if u.strip()
]

# --------------------------------------------------------------------------
# dj-rest-auth
# --------------------------------------------------------------------------
REST_AUTH = {
    "USE_JWT": True,
    "TOKEN_MODEL": None,  # No token auth — project uses SimpleJWT exclusively
    "JWT_AUTH_COOKIE": "app-auth",
    "JWT_AUTH_REFRESH_COOKIE": "app-refresh",
    "JWT_AUTH_HTTPONLY": True,
    "JWT_AUTH_SAMESITE": "Lax",
    "JWT_AUTH_RETURN_EXPIRATION": True,
    # Secure flag on JWT cookies. Set to False in local.py if using
    # cookie-based auth over HTTP (Bearer header auth is unaffected).
    "JWT_AUTH_SECURE": True,
    "USER_DETAILS_SERIALIZER": "accounts.serializers.UserSerializer",
    "JWT_SERIALIZER": "accounts.serializers.CustomJWTSerializer",
}

# --------------------------------------------------------------------------
# SimpleJWT
# --------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    # Separate signing key limits blast radius — compromising
    # SECRET_KEY no longer enables JWT forgery.
    # WARNING: Falls back to SECRET_KEY in non-production environments.
    # Production settings enforce JWT_SIGNING_KEY via validation.
    "SIGNING_KEY": os.getenv("JWT_SIGNING_KEY") or SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --------------------------------------------------------------------------
# AWS
# --------------------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

# --------------------------------------------------------------------------
# SES (Email)
# --------------------------------------------------------------------------
SES_SENDER_EMAIL = os.getenv("SES_SENDER_EMAIL", "")
SES_REGION = os.getenv("SES_REGION", "")  # falls back to AWS_REGION when empty

# --------------------------------------------------------------------------
# Assets (S3-backed file attachments)
# --------------------------------------------------------------------------
# ``ASSET_S3_BUCKET`` is required at upload time (fail-fast in service); not
# enforced at module load so unit tests without the var still import cleanly.
ASSET_S3_BUCKET = os.getenv("ASSET_S3_BUCKET", "")
# Environment scope prefix only (e.g. "uat"); the asset service appends its own
# ``assets/`` folder. Empty (the default) → uploads land directly under ``assets/``.
ASSET_S3_KEY_PREFIX = os.getenv("ASSET_S3_KEY_PREFIX", "")
ASSET_MAX_BYTES = _env_int("ASSET_MAX_BYTES", str(25 * 1024 * 1024))
# Comma-separated MIME allowlist (env-overridable narrowing of AssetMimeType).
# Empty string = use the full enum.
_asset_mime_csv = os.getenv("ASSET_ALLOWED_MIME_TYPES", "").strip()
ASSET_ALLOWED_MIME_TYPES = (
    [m.strip() for m in _asset_mime_csv.split(",") if m.strip()]
    if _asset_mime_csv
    else None
)

# --------------------------------------------------------------------------
# Metrics endpoint (Prometheus prep, NOT yet exporting)
# --------------------------------------------------------------------------
# The /api/metrics URL slot is reserved for future Prometheus scrapes.
# Today the endpoint returns 503 with a documented body; activation is a
# one-line `pip install prometheus-client` + flipping METRICS_ENABLED=True.
# See docs/observability.md for the full activation procedure and the
# cardinality contract that every record_* call site honours.
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "false").lower() in {"1", "true", "yes"}

# --------------------------------------------------------------------------
# Security response headers (SecurityHeadersMiddleware)
# --------------------------------------------------------------------------
# Stamps HSTS / CSP / X-Frame-Options / nosniff / Referrer-Policy /
# Permissions-Policy on every response. HSTS is skipped automatically when
# DJANGO_ENV ∈ {dev,development,test,local} or DEBUG=True so a developer
# hitting http://localhost cannot pin their browser to HTTPS for a year.
SECURITY_HEADERS_ENABLED = _env_bool("SECURITY_HEADERS_ENABLED", "true")
# Comma-separated IP / CIDR allowlist. Default trusts only loopback so the
# endpoint is harmless even when METRICS_ENABLED is on but the network
# perimeter is incomplete.
_metrics_ips = os.getenv("METRICS_ALLOWED_IPS", "127.0.0.1").strip()
METRICS_ALLOWED_IPS = [ip.strip() for ip in _metrics_ips.split(",") if ip.strip()]

# --------------------------------------------------------------------------
# Security headers — explicit values for audit clarity
# --------------------------------------------------------------------------
# Django's defaults already cover most of these, but making them explicit
# closes the audit-finding and protects against a future settings rewrite
# accidentally regressing them.
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# --------------------------------------------------------------------------
# Outbound URL allow-list (defence in depth alongside the SSRF guard in
# core.utils.http_client._assert_public_url). When non-empty, an outbound
# HTTP call to a URL whose hostname doesn't match (suffix or exact) an
# entry is rejected. Empty list = permissive (no allow-listing).
# ``["*"]`` is also permissive — used as the local-dev default so the test
# suite and dev workflow against partner sandboxes don't need to maintain
# the allow-list. Prod and UAT should set this explicitly per environment.
# --------------------------------------------------------------------------
_outbound_allow = os.getenv("OUTBOUND_URL_ALLOWLIST", "*").strip()
OUTBOUND_URL_ALLOWLIST = (
    [e.strip() for e in _outbound_allow.split(",") if e.strip()]
    if _outbound_allow
    else []
)

# --------------------------------------------------------------------------
# Valkey Sentinel (CLIENT-SIDE PREP — no cluster deployed today)
# --------------------------------------------------------------------------
# When VALKEY_SENTINEL_HOSTS is set, the cache + broker clients should switch
# to a Sentinel-aware connection pool. Today these are read but no consumer
# wires them — the per-env settings module owns the cache/broker URL
# construction. See docs/scalability.md.
_sentinel_hosts = os.getenv("VALKEY_SENTINEL_HOSTS", "").strip()
VALKEY_SENTINEL_HOSTS = (
    [h.strip() for h in _sentinel_hosts.split(",") if h.strip()]
    if _sentinel_hosts
    else []
)
VALKEY_SENTINEL_MASTER_NAME = os.getenv("VALKEY_SENTINEL_MASTER_NAME", "")
