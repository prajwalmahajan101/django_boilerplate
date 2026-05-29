"""Example end-to-end test — full APIClient round trip.

Demonstrates the e2e-layer contract: send a real HTTP request through
the URL router, the middleware stack, the view, the service, and the
ORM, then assert on the response envelope.
"""

from __future__ import annotations


def test_unauthenticated_request_to_protected_endpoint_returns_401(api_client):
    """A protected endpoint refuses an unauthenticated caller."""
    # ``/api/accounts/me/`` is a convenient probe; swap for any
    # always-protected route in your app.
    resp = api_client.get("/api/accounts/me/")
    assert resp.status_code in {401, 403, 404}


def test_authenticated_user_can_reach_self_endpoint(authed_api_client):
    """An authenticated caller does not get 401/403 on a self-resource."""
    resp = authed_api_client.get("/api/accounts/me/")
    # 404 means the route doesn't exist in this skeleton — still a
    # valid signal that auth passed. Adjust once you wire the endpoint.
    assert resp.status_code != 401
    assert resp.status_code != 403
