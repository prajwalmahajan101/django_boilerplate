"""Integration-layer fixtures.

Integration tests get the DB by default (``db`` fixture autouse). They
may hit the cache and broker (configured eager in the test settings).
They do NOT use the HTTP client — those tests live in ``tests/e2e/``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_db(db):
    """Every integration test gets DB access without opting in per-test."""
