"""Unit coverage for ``GoogleLogin.get_response``.

The view's URL/dispatch path needs a real OAuth round-trip — out of
scope for this PR. The piece we own (always emit ``refresh`` in the
JSON body when a refresh_token is set on the view) is exercised here
directly with a patched super-call.
"""

from __future__ import annotations

from unittest.mock import patch

from accounts.views import GoogleLogin
from rest_framework.response import Response


def test_get_response_includes_refresh_when_token_set():
    view = GoogleLogin()
    view.refresh_token = "refresh-jwt"

    fake_response = Response({"access": "access-jwt"})
    with patch.object(GoogleLogin.__bases__[0], "get_response", return_value=fake_response):
        out = view.get_response()

    assert out.data["refresh"] == "refresh-jwt"


def test_get_response_leaves_data_untouched_when_no_token_attribute():
    view = GoogleLogin()  # no refresh_token attribute set

    fake_response = Response({"access": "access-jwt"})
    with patch.object(GoogleLogin.__bases__[0], "get_response", return_value=fake_response):
        out = view.get_response()

    assert "refresh" not in out.data
