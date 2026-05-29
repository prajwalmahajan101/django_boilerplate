"""Tests for ``apps.core.runtime``."""

from __future__ import annotations

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from apps.core import runtime


class GetSettingsTests(TestCase):
    def test_returns_django_settings_proxy(self) -> None:
        self.assertIs(runtime.get_settings(), django_settings)


class RequireTests(TestCase):
    def test_returns_value_when_present(self) -> None:
        self.assertEqual(runtime.require("SECRET_KEY"), django_settings.SECRET_KEY)

    @override_settings(DEBUG=False)
    def test_raises_when_missing_in_non_debug(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            runtime.require("DOES_NOT_EXIST_KEY")

    @override_settings(DEBUG=True)
    def test_returns_none_when_missing_in_debug(self) -> None:
        self.assertIsNone(runtime.require("DOES_NOT_EXIST_KEY"))


class ResetTests(TestCase):
    def test_reset_is_noop(self) -> None:
        self.assertIsNone(runtime.reset())
