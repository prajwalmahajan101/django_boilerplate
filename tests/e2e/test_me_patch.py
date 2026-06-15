"""E2E coverage for ``PATCH /api/accounts/me/``.

Confirms the PATCH branch of the ``me`` view delegates to
``UserService.update_profile`` and surfaces ``NoFieldsToUpdateError``
through the standard envelope (registered in ``AccountsConfig.ready()``).
"""

from __future__ import annotations

import pytest


URL = "/api/accounts/me/"


@pytest.mark.django_db
def test_get_returns_profile_envelope(authed_api_client):
    resp = authed_api_client.get(URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == authed_api_client.user.email


@pytest.mark.django_db
def test_patch_happy_path_updates_profile(authed_api_client):
    resp = authed_api_client.patch(
        URL,
        {"first_name": "Alice", "timezone": "America/New_York"},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["first_name"] == "Alice"
    assert data["timezone"] == "America/New_York"


@pytest.mark.django_db
def test_patch_with_no_writable_fields_returns_400(authed_api_client):
    """Empty / no-writable-field PATCH raises NoFieldsToUpdateError -> 400 via the envelope."""
    resp = authed_api_client.patch(URL, {}, format="json")
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["code"] == "NO_FIELDS_TO_UPDATE"
