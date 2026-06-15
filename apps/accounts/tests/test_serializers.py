"""Unit tests for ``apps.accounts.serializers``.

Covers ``GoogleCallbackSerializer.validate_redirect_uri`` allowlist
branches and ``CustomJWTSerializer`` (user resolution, validate / get_token
no-op contract, to_representation expiration passthrough).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from accounts.serializers import CustomJWTSerializer, GoogleCallbackSerializer
from django.test import override_settings
from rest_framework.exceptions import ValidationError


# ---------- GoogleCallbackSerializer.validate_redirect_uri ----------------


@override_settings(GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS=[])
def test_redirect_uri_rejected_when_allowlist_empty():
    serializer = GoogleCallbackSerializer(
        data={"code": "abc", "redirect_uri": "https://app.example.com/cb"}
    )
    assert serializer.is_valid() is False
    assert "redirect_uri" in serializer.errors
    assert "not configured" in str(serializer.errors["redirect_uri"][0])


def test_redirect_uri_rejected_when_setting_missing(settings):
    if hasattr(settings, "GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS"):
        del settings.GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS
    serializer = GoogleCallbackSerializer(
        data={"code": "abc", "redirect_uri": "https://app.example.com/cb"}
    )
    assert serializer.is_valid() is False
    assert "not configured" in str(serializer.errors["redirect_uri"][0])


@override_settings(
    GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS=["https://app.example.com/cb"]
)
def test_redirect_uri_rejected_when_not_in_allowlist():
    serializer = GoogleCallbackSerializer(
        data={"code": "abc", "redirect_uri": "https://evil.example.com/cb"}
    )
    assert serializer.is_valid() is False
    assert "not permitted" in str(serializer.errors["redirect_uri"][0])


@override_settings(
    GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS=["https://app.example.com/cb"]
)
def test_redirect_uri_passes_when_in_allowlist():
    serializer = GoogleCallbackSerializer(
        data={"code": "abc", "redirect_uri": "https://app.example.com/cb"}
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["redirect_uri"] == (
        "https://app.example.com/cb"
    )


@override_settings(
    GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS=["https://app.example.com/cb"]
)
def test_redirect_uri_validate_method_returns_value_unchanged():
    serializer = GoogleCallbackSerializer()
    assert serializer.validate_redirect_uri("https://app.example.com/cb") == (
        "https://app.example.com/cb"
    )


@override_settings(GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS=[])
def test_redirect_uri_validate_method_raises_when_unconfigured():
    serializer = GoogleCallbackSerializer()
    with pytest.raises(ValidationError):
        serializer.validate_redirect_uri("https://app.example.com/cb")


# ---------- CustomJWTSerializer ------------------------------------------


def test_jwt_get_user_returns_none_when_obj_has_no_user():
    serializer = CustomJWTSerializer()
    assert serializer.get_user({"user": None}) is None


def test_jwt_get_user_returns_none_when_key_missing():
    serializer = CustomJWTSerializer()
    assert serializer.get_user({}) is None


def test_jwt_get_user_returns_serialized_user_dict():
    user = MagicMock()
    user.id = 7
    user.email = "u@example.com"
    user.first_name = "U"
    user.last_name = "Ser"
    user.full_name = "U Ser"
    user.avatar_url = ""
    user.timezone = "UTC"
    user.email_verified = True
    user.date_joined = None
    user.last_login = None
    user.roles.all.return_value = []
    user.socialaccount_set.filter.return_value.exists.return_value = False

    serializer = CustomJWTSerializer()
    data = serializer.get_user({"user": user})
    assert isinstance(data, dict)
    assert data["email"] == "u@example.com"


def test_jwt_validate_is_a_noop():
    serializer = CustomJWTSerializer()
    payload = {"foo": "bar"}
    assert serializer.validate(payload) is payload


def test_jwt_get_token_is_a_noop_classmethod():
    payload = {"any": "data"}
    assert CustomJWTSerializer.get_token(payload) is payload


def test_jwt_to_representation_adds_expirations_when_present():
    serializer = CustomJWTSerializer(
        instance={
            "access": "a",
            "refresh": "r",
            "user": None,
            "access_expiration": "2099-01-01T00:00:00Z",
            "refresh_expiration": "2099-02-01T00:00:00Z",
        }
    )
    data = serializer.data
    assert data["access_expiration"] == "2099-01-01T00:00:00Z"
    assert data["refresh_expiration"] == "2099-02-01T00:00:00Z"


def test_jwt_to_representation_omits_expirations_when_absent():
    serializer = CustomJWTSerializer(
        instance={"access": "a", "refresh": "r", "user": None}
    )
    data = serializer.data
    assert "access_expiration" not in data
    assert "refresh_expiration" not in data
