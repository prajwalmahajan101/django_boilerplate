"""Tests for ``BackendHealth`` semantics and the dual-recovery model.

These tests cover the structural contract — full behavioural tests of
the recovery monitor against a real Valkey are out of scope (covered by
integration tests against the docker-compose stack).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.resilience.health import BackendHealth
from core.resilience.recovery import (
    attempt_recover_all,
    register_for_recovery,
    registered_backends,
    reset_backend,
)


class _StubBackend:
    """Minimal RecoverableBackend implementation for unit tests."""

    def __init__(self, alias: str, health: BackendHealth) -> None:
        self.alias = alias
        self._health = health
        self.try_recover_called = 0

    @property
    def health(self) -> BackendHealth:
        return self._health

    def try_recover(self) -> bool:
        self.try_recover_called += 1
        # Simulate a successful flip.
        if self._health is BackendHealth.DEGRADED:
            self._health = BackendHealth.ACTIVE
            return True
        return False


class BackendHealthTests(SimpleTestCase):
    def test_three_states_with_helpers(self) -> None:
        self.assertTrue(BackendHealth.ACTIVE.is_healthy)
        self.assertFalse(BackendHealth.DEGRADED.is_healthy)
        self.assertFalse(BackendHealth.BOOT_FALLBACK.is_healthy)
        self.assertFalse(BackendHealth.DEGRADED.needs_object_rebuild)
        self.assertTrue(BackendHealth.BOOT_FALLBACK.needs_object_rebuild)


class RecoveryDispatchTests(SimpleTestCase):
    def test_degraded_backend_recovered_via_try_recover(self) -> None:
        backend = _StubBackend("cache:test-degraded", BackendHealth.DEGRADED)
        register_for_recovery(backend)
        recovered = attempt_recover_all()
        self.assertGreaterEqual(recovered, 1)
        self.assertEqual(backend.try_recover_called, 1)
        self.assertIs(backend.health, BackendHealth.ACTIVE)

    def test_boot_fallback_does_not_call_try_recover(self) -> None:
        backend = _StubBackend("cache:test-bootfb", BackendHealth.BOOT_FALLBACK)
        register_for_recovery(backend)
        # reset_backend("cache:...") routes to cache provider; we patch
        # the provider call to confirm the BOOT_FALLBACK dispatch path.
        with patch(
            "core.resilience.cache.provider.reset_cache_backend",
            return_value=True,
        ) as mock_reset:
            attempt_recover_all()
        mock_reset.assert_called_once_with("test-bootfb")
        self.assertEqual(backend.try_recover_called, 0)

    def test_active_backend_is_a_noop(self) -> None:
        backend = _StubBackend("cache:test-active", BackendHealth.ACTIVE)
        register_for_recovery(backend)
        attempt_recover_all()
        self.assertEqual(backend.try_recover_called, 0)


class ResetBackendDispatchTests(SimpleTestCase):
    def test_unknown_alias_returns_false(self) -> None:
        self.assertFalse(reset_backend("mystery:foo"))

    def test_dispatches_to_throttle_provider(self) -> None:
        with patch(
            "core.resilience.throttles.provider.reset_throttle_backend",
            return_value=True,
        ) as mock_reset:
            ok = reset_backend("throttle:counters")
        self.assertTrue(ok)
        mock_reset.assert_called_once_with("counters")

    def test_dispatches_to_breaker_provider(self) -> None:
        with patch(
            "core.resilience.circuit_breaker.provider.reset_breaker_registry",
            return_value=True,
        ) as mock_reset:
            ok = reset_backend("breaker:registry")
        self.assertTrue(ok)
        mock_reset.assert_called_once_with()
