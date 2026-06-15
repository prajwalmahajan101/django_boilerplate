"""Integration test: real Valkey set/get round-trip + DB-index isolation.

Test settings (``config/settings/test.py``) hard-code ``LocMemCache``
so the rest of the suite stays fast and offline. This test opts INTO
real Valkey via ``override_settings`` scoped to its module — no global
settings swap, no leakage into other test files.

Skipped unless ``VALKEY_AVAILABLE=1`` is set in the environment (CI
sets it after the ``valkey/valkey:7`` service container reports
healthy). Locally, contributors can run::

    docker run --rm -p 6379:6379 valkey/valkey:7
    VALKEY_AVAILABLE=1 DJANGO_ENV=test pytest tests/integration/test_valkey_roundtrip.py
"""

from __future__ import annotations

import os

import pytest
from django.core.cache import caches
from django.test import override_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("VALKEY_AVAILABLE") != "1",
        reason="real Valkey not provisioned (set VALKEY_AVAILABLE=1 + run "
        "valkey/valkey:7 on 127.0.0.1:6379)",
    ),
]


_HOST = os.getenv("VALKEY_HOST", "127.0.0.1")
_PORT = os.getenv("VALKEY_PORT", "6379")

_VALKEY_CACHES = {
    "default": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": f"valkey://{_HOST}:{_PORT}/2",
        "OPTIONS": {"CLIENT_CLASS": "django_valkey.client.DefaultClient"},
    },
    "rate_limit": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": f"valkey://{_HOST}:{_PORT}/3",
        "OPTIONS": {"CLIENT_CLASS": "django_valkey.client.DefaultClient"},
    },
}


@pytest.fixture
def real_valkey():
    """Swap CACHES to real Valkey for one test, then restore.

    Django's ``override_settings`` fires ``setting_changed`` signals that
    Django's own ``django.test.signals.clear_cache_handlers`` listens to,
    which resets the ``caches`` registry — so we don't need to poke at
    ``CacheHandler`` internals.
    """
    with override_settings(CACHES=_VALKEY_CACHES):
        yield


def _flush(name: str) -> None:
    caches[name].clear()


def test_real_valkey_set_get_roundtrip(real_valkey):
    """Round-trip a value through the real django-valkey backend."""
    _flush("default")
    cache = caches["default"]
    cache.set("m2:roundtrip", {"hello": "valkey"}, timeout=30)
    assert cache.get("m2:roundtrip") == {"hello": "valkey"}


def test_default_and_rate_limit_caches_use_different_db_indexes(real_valkey):
    """Same key in 'default' and 'rate_limit' must not collide.

    The two caches are configured against different Valkey DB indexes
    (2 and 3 respectively). Writing to one and reading from the other
    should miss — that's the isolation contract callers rely on so
    rate-limit buckets don't bleed into general cache and vice versa.
    """
    _flush("default")
    _flush("rate_limit")

    caches["default"].set("m2:shared-key", "in-default", timeout=30)
    assert caches["default"].get("m2:shared-key") == "in-default"
    assert caches["rate_limit"].get("m2:shared-key") is None

    caches["rate_limit"].set("m2:shared-key", "in-rate-limit", timeout=30)
    assert caches["rate_limit"].get("m2:shared-key") == "in-rate-limit"
    # Writing to rate_limit must not overwrite default's value.
    assert caches["default"].get("m2:shared-key") == "in-default"
