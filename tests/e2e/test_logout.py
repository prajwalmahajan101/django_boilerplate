"""E2E coverage for the ``logout`` view.

POST /api/accounts/logout/ — accepts a refresh token belonging to the
authenticated user and blacklists it. Covers the 400 / 401 / 200
branches plus the ownership boundary that distinguishes "any valid
token" from "this user's token".
"""

from __future__ import annotations

import pytest
from rest_framework_simplejwt.tokens import RefreshToken

URL = "/api/accounts/logout/"


def test_missing_refresh_returns_400(authed_api_client):
    resp = authed_api_client.post(URL, {}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_happy_path_blacklists_token(authed_api_client):
    refresh = str(RefreshToken.for_user(authed_api_client.user))
    resp = authed_api_client.post(URL, {"refresh": refresh}, format="json")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Successfully logged out."


@pytest.mark.django_db
def test_token_belonging_to_other_user_rejected(authed_api_client, user_factory):
    other = user_factory(email="other@example.com", username="other-user")
    refresh = str(RefreshToken.for_user(other))

    resp = authed_api_client.post(URL, {"refresh": refresh}, format="json")
    assert resp.status_code == 401


def test_invalid_token_string_returns_401(authed_api_client):
    resp = authed_api_client.post(URL, {"refresh": "not-a-jwt"}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_token_with_non_integer_user_id_returns_401(authed_api_client):
    """A refresh token whose ``user_id`` claim is not int-coercible triggers the ValueError branch."""
    refresh = RefreshToken.for_user(authed_api_client.user)
    refresh["user_id"] = "not-an-integer"
    resp = authed_api_client.post(URL, {"refresh": str(refresh)}, format="json")
    assert resp.status_code == 401
