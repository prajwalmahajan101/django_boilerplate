"""Tests for ``core.testing.reset_all_singletons``."""

from __future__ import annotations

from django.test import TestCase

from core.testing import reset_all_singletons


class ResetAllSingletonsTests(TestCase):
    def test_runs_without_error_on_fresh_state(self) -> None:
        reset_all_singletons()

    def test_clears_django_cache(self) -> None:
        from django.core.cache import cache

        cache.set("k", "v")
        self.assertEqual(cache.get("k"), "v")
        reset_all_singletons()
        self.assertIsNone(cache.get("k"))

    def test_clears_fernet_cache(self) -> None:
        from core.utils import crypto

        crypto._fernet()
        self.assertGreater(crypto._fernet.cache_info().currsize, 0)
        reset_all_singletons()
        self.assertEqual(crypto._fernet.cache_info().currsize, 0)
