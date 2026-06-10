"""Top-level pytest configuration.

Repo-wide fixtures live here. Per-app fixtures live in
``apps/<name>/tests/conftest.py``. Per-layer fixtures live in
``tests/{unit,integration,e2e}/conftest.py``.

Layer convention:

* ``tests/unit/`` — no DB / no cache / no HTTP. Use mocks for every
  boundary. Marked ``@pytest.mark.unit`` (or just live under the dir).
* ``tests/integration/`` — DB, cache, broker allowed. No HTTP client.
  Marked ``@pytest.mark.integration``.
* ``tests/e2e/`` — full ``APIClient`` round-trip through views,
  serializers, services, ORM. Marked ``@pytest.mark.e2e``.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Layer auto-marking
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    """Auto-apply layer markers based on test file path.

    Tests under ``tests/unit/`` → ``@pytest.mark.unit``.
    Tests under ``tests/integration/`` → ``@pytest.mark.integration``.
    Tests under ``tests/e2e/`` → ``@pytest.mark.e2e``.
    Tests under ``apps/*/tests/`` → ``@pytest.mark.unit`` by default
    (override per-test with ``@pytest.mark.integration`` when they hit
    the DB).
    """
    for item in items:
        path = str(item.fspath)
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
        elif "/apps/" in path and "/tests/" in path:
            # App-co-located tests default to unit unless the test
            # explicitly opts into another layer.
            if not any(m.name in {"unit", "integration", "e2e"} for m in item.iter_markers()):
                item.add_marker(pytest.mark.unit)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """Unauthenticated DRF ``APIClient`` instance."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user_factory(db):
    """Callable that creates a ``User`` with sane defaults.

    Usage::

        def test_x(user_factory):
            u = user_factory(email="alice@example.com")
    """
    from tests.factories import UserFactory

    def _make(**overrides):
        return UserFactory(**overrides)

    return _make


@pytest.fixture
def user(user_factory):
    """A single freshly-created active user."""
    return user_factory()


@pytest.fixture
def authed_api_client(api_client, user):
    """``APIClient`` already authenticated as a fresh user."""
    api_client.force_authenticate(user=user)
    api_client.user = user  # convenience handle for assertions
    return api_client


@pytest.fixture
def superuser_api_client(api_client, user_factory):
    """``APIClient`` authenticated as a Django superuser."""
    su = user_factory(is_staff=True, is_superuser=True)
    api_client.force_authenticate(user=su)
    api_client.user = su
    return api_client


@pytest.fixture
def settings_override(settings):
    """Shorthand for ``pytest-django``'s ``settings`` fixture.

    Reads more clearly at the call site::

        def test_x(settings_override):
            settings_override.FOO = "bar"
    """
    return settings


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset process-level singletons between tests.

    Prevents bleed of cache / throttle / breaker / queue / Fernet
    state between test cases on the same process. Single source of
    truth lives in ``core.testing.reset_all_singletons``.
    """
    # Kit-owned singletons (registry, breakers, throttle buckets, audit
    # dispatcher, settings cache, recovery state) reset via the kit's
    # canonical reset entry point so any new singleton added kit-side
    # gets reset automatically without a boilerplate-side edit.
    from resilience_kit.testing.reset import reset_all_singletons

    yield
    reset_all_singletons()
