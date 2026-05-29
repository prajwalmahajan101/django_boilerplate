"""Unit tests for ``core.utils.network.client_ip``.

Matrix:
  * ``USE_X_FORWARDED_FOR`` on/off
  * ``X-Forwarded-For`` / ``X-Real-IP`` / ``REMOTE_ADDR`` / missing

The trust-proxy switch is read at call time (``getattr(settings, ...)``)
so we can flip it with ``override_settings`` per test.
"""

from __future__ import annotations

from core.utils.network import client_ip
from django.test import RequestFactory, SimpleTestCase, override_settings


class ClientIpTrustedProxyOnTest(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    @override_settings(USE_X_FORWARDED_FOR=True)
    def test_first_hop_of_xff_wins(self):
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1",
            HTTP_X_REAL_IP="198.51.100.7",
            REMOTE_ADDR="10.0.0.2",
        )
        self.assertEqual(client_ip(request), "203.0.113.5")

    @override_settings(USE_X_FORWARDED_FOR=True)
    def test_falls_back_to_real_ip_when_xff_missing(self):
        request = self.factory.get(
            "/",
            HTTP_X_REAL_IP="198.51.100.7",
            REMOTE_ADDR="10.0.0.2",
        )
        self.assertEqual(client_ip(request), "198.51.100.7")

    @override_settings(USE_X_FORWARDED_FOR=True)
    def test_falls_back_to_remote_addr_when_proxy_headers_missing(self):
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.2")
        self.assertEqual(client_ip(request), "10.0.0.2")


class ClientIpTrustedProxyOffTest(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    @override_settings(USE_X_FORWARDED_FOR=False)
    def test_xff_ignored_when_proxy_not_trusted(self):
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="203.0.113.5",
            HTTP_X_REAL_IP="198.51.100.7",
            REMOTE_ADDR="10.0.0.2",
        )
        self.assertEqual(client_ip(request), "10.0.0.2")

    @override_settings(USE_X_FORWARDED_FOR=False)
    def test_returns_unknown_when_no_peer(self):
        request = self.factory.get("/")
        request.META.pop("REMOTE_ADDR", None)
        self.assertEqual(client_ip(request), "unknown")
