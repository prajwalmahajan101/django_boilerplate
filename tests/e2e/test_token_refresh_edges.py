"""E2E coverage for ``token_refresh`` error branches.

Complements ``test_token_refresh_rotation.py`` (happy + blacklist-503)
with the 4xx branches: missing token, invalid string, deactivated user,
deleted user.
"""

from __future__ import annotations

import pytest
from rest_framework_simplejwt.tokens import RefreshToken


URL = "/api/accounts/token/refresh/"


def test_missing_refresh_returns_400(api_client):
    resp = api_client.post(URL, {}, format="json")
    assert resp.status_code == 400


def test_invalid_token_string_returns_401(api_client):
    resp = api_client.post(URL, {"refresh": "not-a-jwt"}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_inactive_user_cannot_refresh(api_client, user):
    refresh = str(RefreshToken.for_user(user))
    user.is_active = False
    user.save(update_fields=["is_active"])

    resp = api_client.post(URL, {"refresh": refresh}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_deleted_user_cannot_refresh(api_client, user):
    refresh = str(RefreshToken.for_user(user))
    user.delete()

    resp = api_client.post(URL, {"refresh": refresh}, format="json")
    assert resp.status_code == 401
