"""End-to-end-layer fixtures.

E2E tests drive the API through DRF's ``APIClient``. They get the DB
by default and inherit the ``api_client`` / ``authed_api_client``
fixtures from the top-level conftest.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_throttle_cache():
    """Clear DRF throttle buckets between tests.

    ``BurstThrottle`` + ``AuthEndpointThrottle`` key on client IP. The
    ``test`` settings module uses ``LocMemCache``, which persists across
    tests in the same process — a single e2e file that POSTs to an auth
    endpoint more than the burst limit from the fixture-supplied IP
    would otherwise hit 429.
    """
    from django.core.cache import caches

    for alias in caches:
        caches[alias].clear()


@pytest.fixture(autouse=True)
def _enable_db(db):
    """Every E2E test gets DB access without opting in per-test."""
