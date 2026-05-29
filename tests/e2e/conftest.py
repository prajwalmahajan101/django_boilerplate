"""End-to-end-layer fixtures.

E2E tests drive the API through DRF's ``APIClient``. They get the DB
by default and inherit the ``api_client`` / ``authed_api_client``
fixtures from the top-level conftest.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_db(db):
    """Every E2E test gets DB access without opting in per-test."""
