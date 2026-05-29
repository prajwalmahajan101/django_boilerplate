import importlib as _importlib
import json
import os
import sys as _sys
from pathlib import Path

from dotenv import load_dotenv

# --- apps/ on sys.path (ISSUE-011) ------------------------------------------
# This block is duplicated verbatim in config/celery.py. It cannot be
# extracted to a shared helper because config/__init__.py imports celery,
# so any `from config._x import …` here would re-enter config/__init__.py
# → circular import. Keep both copies identical; if you change this block,
# change the sibling at config/celery.py too.
_apps_dir = str(Path(__file__).resolve().parent.parent.parent / "apps")
if _apps_dir not in _sys.path:
    _sys.path.insert(0, _apps_dir)
# Boot-time drift guard: recompute what config/celery.py *would* resolve to
# and refuse to start if the two siblings disagree. Catches the only realistic
# failure mode of the duplication (someone edits one copy without the other).
# Both files anchor on the project root (``parents[2]`` from the settings
# package, ``parents[1]`` from config/celery.py — equal by construction).
_celery_apps_dir = str(Path(__file__).resolve().parents[2] / "apps")
if _apps_dir != _celery_apps_dir:
    raise RuntimeError(
        f"sys.path drift between config/settings/__init__.py ({_apps_dir!r}) "
        f"and config/celery.py ({_celery_apps_dir!r}). Re-sync the two blocks."
    )
# ----------------------------------------------------------------------------

# DJANGO_ENV must be explicitly set — no default.
env = os.getenv("DJANGO_ENV")
if not env:
    raise ValueError(
        "DJANGO_ENV environment variable is not set. "
        "Set it to one of: local, dev, prod, test (e.g. DJANGO_ENV=local)."
    )

_VALID_ENVS = ("local", "dev", "uat", "prod", "test")
if env not in _VALID_ENVS:
    raise ValueError(
        f"Invalid DJANGO_ENV='{env}'. Expected one of: {', '.join(_VALID_ENVS)}"
    )


def _load_secrets_from_aws(secret_name, region_name="ap-south-1"):
    """Load secrets from AWS Secrets Manager."""
    import boto3
    from botocore.exceptions import ClientError

    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        import warnings

        warnings.warn(
            f"FATAL: Failed to retrieve secret '{secret_name}' from AWS Secrets Manager: {e}. "
            "Application cannot start with missing configuration.",
            RuntimeWarning,
            stacklevel=2,
        )
        raise RuntimeError(
            f"Cannot start application: AWS Secrets Manager is unreachable or "
            f"secret '{secret_name}' does not exist. Error: {e}"
        ) from e

    if "SecretString" in response:
        return json.loads(response["SecretString"])
    return {}


# ---------------------------------------------------------------------------
# Load environment variables from environment/ directory
# ---------------------------------------------------------------------------
# config/settings/__init__.py -> config/settings/ -> config/ -> project root
_project_root = Path(__file__).resolve().parent.parent.parent
_env_dir = _project_root / "environment"

if env == "test":
    # Test env skips .env loading — test settings are self-contained.
    pass

elif env in ("local", "dev", "uat", "prod"):
    env_file = _env_dir / f".env.{env}"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    # UAT intentionally skips Secrets Manager — keeps the bring-up simple and
    # leaves Secrets Manager wiring for prod where rotation matters most.
    if env in ("dev", "prod"):
        secret_name = os.getenv("AWS_SECRET_NAME")
        if secret_name:
            region_name = os.getenv("AWS_REGION", "ap-south-1")
            try:
                secrets = _load_secrets_from_aws(secret_name, region_name)
                for key, value in secrets.items():
                    if key not in os.environ:
                        os.environ[key] = str(value)
            except RuntimeError as exc:
                # Prod must never silently fall back to the .env file:
                # those values are typically placeholder credentials, and
                # booting on them would run the live service against the
                # wrong backends or with a guessable secret.
                if env == "prod":
                    raise RuntimeError(
                        f"AWS Secrets Manager unavailable in prod "
                        f"(secret={secret_name!r}): refusing to boot on .env fallback"
                    ) from exc

                import warnings

                warnings.warn(
                    "AWS Secrets Manager unavailable — using .env values only.",
                    RuntimeWarning,
                    stacklevel=2,
                )

# ---------------------------------------------------------------------------
# Dynamically import the environment-specific settings module
# ---------------------------------------------------------------------------
_env_module = _importlib.import_module(f".{env}", __name__)

# Merge all public settings from the env module into this namespace
_this_module = _sys.modules[__name__]
for _attr in dir(_env_module):
    if not _attr.startswith("_"):
        setattr(_this_module, _attr, getattr(_env_module, _attr))

# Expose which settings module is active for debugging / traceability
SETTINGS_MODULE = f"config.settings.{env}"

# ---------------------------------------------------------------------------
# Logging (applied after env merge so LOG_LEVEL is available)
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "core.utils.logging.RequestContextFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(request_id)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_context"],
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        # Suppress redundant Django loggers — custom middleware provides
        # richer context (user, request_id, duration).
        "django.server": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "": {  # Root logger
            "handlers": ["console"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
        },
    },
}

# Add CloudWatch handler if enabled
if os.getenv("CLOUDWATCH_ENABLED") == "TRUE":
    LOGGING["handlers"]["cloudwatch"] = {
        "level": "INFO",
        "class": "cloudwatch.cloudwatch.CloudwatchHandler",
        "formatter": "json",
        "log_group": os.getenv("CLOUDWATCH_LOG_GROUP"),
        "region": os.getenv("AWS_REGION"),
    }
    LOGGING["loggers"]["django"]["handlers"].append("cloudwatch")
    LOGGING["loggers"][""]["handlers"].append("cloudwatch")

# ---------------------------------------------------------------------------
# Sentry (applied after env merge)
# ---------------------------------------------------------------------------
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
# Be defensive about malformed values (e.g. inline-comment leftovers from a
# copied template). Only initialize Sentry when the DSN looks like a real URL.
if _sentry_dsn.startswith(("https://", "http://")):
    import sentry_sdk

    try:
        _traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    except (ValueError, TypeError):
        _traces_rate = 0.1

    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=env,
        release=os.getenv("APP_VERSION", "unknown"),
        traces_sample_rate=_traces_rate,
        _experiments={
            "continuous_profiling_auto_start": True,
        },
    )
