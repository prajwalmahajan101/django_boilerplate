"""E2E coverage for ``APIKeyDeleteView`` and ``APIKeyRevokeView``.

The service-layer contract is pinned in
``apps/accounts/tests/test_api_key_revoke.py``; this file drives the
same endpoints through the URL/permission/dispatch stack so the view
wrappers (404 mapping, idempotency response message, status codes) are
exercised end-to-end.
"""

from __future__ import annotations

import pytest
from accounts.models import APIKey, Role


@pytest.fixture
def superuser_role_client(authed_api_client):
    """Give the test user a superuser role so HasResourcePermission passes."""
    role = Role.objects.create(name="superadmin", is_superuser_role=True)
    authed_api_client.user.roles.add(role)
    # cached_property — drop any prior cache so the new role is seen.
    authed_api_client.user.__dict__.pop("has_superuser_role", None)
    return authed_api_client


@pytest.fixture
def api_key(authed_api_client):
    instance, _raw = APIKey.create_key(
        user=authed_api_client.user,
        name="test-key",
        created_by=authed_api_client.user,
    )
    return instance


@pytest.mark.django_db
def test_delete_missing_pk_returns_404(superuser_role_client):
    resp = superuser_role_client.delete("/api/accounts/api-keys/999999/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_existing_key_returns_200(superuser_role_client, api_key):
    resp = superuser_role_client.delete(f"/api/accounts/api-keys/{api_key.pk}/")
    assert resp.status_code == 200
    assert resp.json()["message"] == "API key deleted."


@pytest.mark.django_db
def test_revoke_missing_pk_returns_404(superuser_role_client):
    resp = superuser_role_client.post(
        "/api/accounts/api-keys/999999/revoke/"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_revoke_first_call_returns_revoked_message(superuser_role_client, api_key):
    resp = superuser_role_client.post(
        f"/api/accounts/api-keys/{api_key.pk}/revoke/"
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "API key revoked."


@pytest.mark.django_db
def test_revoke_second_call_is_idempotent(superuser_role_client, api_key):
    url = f"/api/accounts/api-keys/{api_key.pk}/revoke/"
    superuser_role_client.post(url)
    resp = superuser_role_client.post(url)
    assert resp.status_code == 200
    assert resp.json()["message"] == "API key already revoked."
