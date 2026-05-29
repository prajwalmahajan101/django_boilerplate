"""Token-refresh rotation safety (ISSUE-009).

The old code minted a new token BEFORE blacklisting the old one. If
blacklist failed, the user briefly held two valid refresh tokens.

The fix inverts the order: blacklist first, mint second, and surface
blacklist failures as 503 so the client retries with the still-valid
old token instead of receiving a second pair.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


@pytest.fixture
def refresh_token_for(user):
    """Helper: mint a real refresh token for the given user."""

    def _make(u=None):
        return str(RefreshToken.for_user(u or user))

    return _make


def test_blacklist_failure_returns_503_and_no_new_pair(api_client, user, refresh_token_for):
    """Blacklist failure surfaces as 503; response body omits new tokens."""
    refresh = refresh_token_for()

    with patch.object(RefreshToken, "blacklist", side_effect=TokenError("backend down")):
        resp = api_client.post(
            "/api/accounts/token/refresh/",
            {"refresh": refresh},
            format="json",
        )

    assert resp.status_code == 503
    body = resp.json()
    assert "access" not in (body.get("data") or {})
    assert "refresh" not in (body.get("data") or {})


def test_happy_path_returns_new_pair(api_client, user, refresh_token_for):
    """Without backend faults, rotation issues a new access+refresh pair."""
    refresh = refresh_token_for()
    resp = api_client.post(
        "/api/accounts/token/refresh/",
        {"refresh": refresh},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access"]
    assert data["refresh"]
    # Tokens get rotated — new refresh != old refresh
    assert data["refresh"] != refresh
