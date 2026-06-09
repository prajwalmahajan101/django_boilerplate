"""Tests for ``core.auth`` registry + ``CompositeAuthentication``."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from core.auth import (
    CompositeAuthentication,
    enabled_providers,
    register,
    registered_names,
    unregister,
)
from core.auth import registry as registry_module
from django.test import override_settings


@pytest.fixture
def isolated_registry():
    """Snapshot + restore the auth registry around each test."""
    snapshot = dict(registry_module._REGISTRY)
    warned = set(registry_module._WARNED_UNKNOWN)
    registry_module._REGISTRY.clear()
    registry_module._WARNED_UNKNOWN.clear()
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(snapshot)
    registry_module._WARNED_UNKNOWN.clear()
    registry_module._WARNED_UNKNOWN.update(warned)


def _provider(name: str, result=None):
    p = MagicMock()
    p.name = name
    p.authenticate.return_value = result
    return p


class TestRegistry:
    def test_register_and_unregister(self, isolated_registry):
        p = _provider("api_key")
        register(p)
        assert "api_key" in registered_names()
        unregister("api_key")
        assert "api_key" not in registered_names()

    def test_register_replaces_existing(self, isolated_registry):
        a, b = _provider("jwt"), _provider("jwt")
        register(a)
        register(b)
        assert len(registered_names()) == 1

    @override_settings(AUTH_ENABLED_PROVIDERS=["jwt", "api_key"])
    def test_enabled_providers_honours_order(self, isolated_registry):
        jwt, api = _provider("jwt"), _provider("api_key")
        register(api)
        register(jwt)
        order = [p.name for p in enabled_providers()]
        assert order == ["jwt", "api_key"]

    @override_settings(AUTH_ENABLED_PROVIDERS=["jwt", "bogus"])
    def test_unknown_provider_warns_once(self, isolated_registry, caplog):
        register(_provider("jwt"))
        with caplog.at_level(logging.WARNING):
            enabled_providers()
            enabled_providers()
        warnings = [r for r in caplog.records if "bogus" in r.getMessage()]
        assert len(warnings) == 1


class TestCompositeAuthentication:
    @override_settings(AUTH_ENABLED_PROVIDERS=["jwt", "api_key"])
    def test_first_match_wins(self, isolated_registry):
        sentinel = ("user", "auth")
        register(_provider("jwt", result=sentinel))
        api = _provider("api_key", result=("other", "auth2"))
        register(api)

        result = CompositeAuthentication().authenticate(MagicMock())
        assert result == sentinel
        api.authenticate.assert_not_called()

    @override_settings(AUTH_ENABLED_PROVIDERS=["jwt", "api_key"])
    def test_none_falls_through(self, isolated_registry):
        register(_provider("jwt", result=None))
        sentinel = ("u", "a")
        register(_provider("api_key", result=sentinel))
        assert CompositeAuthentication().authenticate(MagicMock()) == sentinel

    @override_settings(AUTH_ENABLED_PROVIDERS=["jwt"])
    def test_raise_propagates_and_stops_chain(self, isolated_registry):
        from rest_framework.exceptions import AuthenticationFailed

        bad = _provider("jwt")
        bad.authenticate.side_effect = AuthenticationFailed("nope")
        register(bad)
        with pytest.raises(AuthenticationFailed):
            CompositeAuthentication().authenticate(MagicMock())

    @override_settings(AUTH_ENABLED_PROVIDERS=[])
    def test_no_providers_returns_none(self, isolated_registry):
        assert CompositeAuthentication().authenticate(MagicMock()) is None
