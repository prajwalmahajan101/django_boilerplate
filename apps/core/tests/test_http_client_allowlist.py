"""Tests for ``OUTBOUND_URL_ALLOWLIST`` and the DNS-pinned SSRF guard."""

from __future__ import annotations

import socket
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.base.exception import BaseCustomError
from core.utils.http_client import (
    _assert_url_allowlisted,
    _orig_getaddrinfo,
    _pinned_dns,
    _resolve_and_validate,
    make_http_request,
)


class OutboundAllowlistTests(SimpleTestCase):
    @override_settings(OUTBOUND_URL_ALLOWLIST=["*"])
    def test_wildcard_accepts_everything(self) -> None:
        _assert_url_allowlisted("https://anywhere.example.com/x")

    @override_settings(OUTBOUND_URL_ALLOWLIST=[])
    def test_empty_list_is_permissive(self) -> None:
        # Documented: empty list = unconfigured = permissive.
        _assert_url_allowlisted("https://anywhere.example.com/x")

    @override_settings(OUTBOUND_URL_ALLOWLIST=["partner.example.com"])
    def test_exact_match_accepted(self) -> None:
        _assert_url_allowlisted("https://partner.example.com/api/x")

    @override_settings(OUTBOUND_URL_ALLOWLIST=["partner.example.com"])
    def test_unknown_host_rejected(self) -> None:
        with self.assertRaises(BaseCustomError) as ctx:
            _assert_url_allowlisted("https://typo.example.com/x")
        self.assertIn("not in OUTBOUND_URL_ALLOWLIST", str(ctx.exception))

    @override_settings(OUTBOUND_URL_ALLOWLIST=[".example.com"])
    def test_suffix_match_accepts_subdomain(self) -> None:
        _assert_url_allowlisted("https://api.example.com/x")
        _assert_url_allowlisted("https://example.com/x")

    @override_settings(OUTBOUND_URL_ALLOWLIST=[".example.com"])
    def test_suffix_match_rejects_neighbour(self) -> None:
        with self.assertRaises(BaseCustomError):
            _assert_url_allowlisted("https://malicious-example.com/x")


class TrustedFlagAllowlistTests(SimpleTestCase):
    """Pin that ``trusted=True`` opts out of SSRF but NOT of the allowlist.

    Regression for ISSUE-228: an admin-configured partner URL must still
    be evaluated against ``OUTBOUND_URL_ALLOWLIST``, because the allowlist
    is the deploy-time sanctioned-destination check — it answers a different
    question from the SSRF private-IP guard.
    """

    @override_settings(OUTBOUND_URL_ALLOWLIST=["partner.example.com"])
    def test_trusted_does_not_bypass_allowlist(self) -> None:
        with self.assertRaises(BaseCustomError) as ctx:
            make_http_request(
                method="GET",
                url="https://attacker.example.com/x",
                trusted=True,
            )
        self.assertIn("not in OUTBOUND_URL_ALLOWLIST", str(ctx.exception))

    @override_settings(OUTBOUND_URL_ALLOWLIST=["partner.example.com"])
    def test_trusted_allowlisted_host_is_accepted(self) -> None:
        with patch("core.utils.http_client._client._do_request") as do_request:
            do_request.return_value = object()
            result = make_http_request(
                method="GET",
                url="https://partner.example.com/api/x",
                trusted=True,
                max_attempts=1,
            )
        do_request.assert_called_once()
        self.assertIs(result, do_request.return_value)


class DNSPinningTests(SimpleTestCase):
    """Regression tests for the DNS-rebinding TOCTOU (ISSUE-028)."""

    def _addrinfo(self, ip: str):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]

    @override_settings(SSRF_BLOCK_PRIVATE_IPS=True)
    def test_resolve_and_validate_returns_addrs(self) -> None:
        """_resolve_and_validate returns the IPs it validated so they can be pinned."""
        with patch("core.utils.http_client._client.socket.getaddrinfo", return_value=self._addrinfo("8.8.8.8")):
            host, addrs = _resolve_and_validate("https://attacker.example/x", strict=True)
        self.assertEqual(host, "attacker.example")
        self.assertEqual(addrs, ["8.8.8.8"])

    @override_settings(SSRF_BLOCK_PRIVATE_IPS=True)
    def test_pinned_resolution_survives_rebind(self) -> None:
        """Validation returns public IP; a subsequent getaddrinfo via the
        patched resolver returns the *pinned* IPs even though an attacker
        flipped DNS to a private address. This is the regression that would
        have failed before the pin landed."""
        # Validation phase: DNS returns a public IP.
        with patch("core.utils.http_client._client.socket.getaddrinfo", return_value=self._addrinfo("8.8.8.8")):
            host, addrs = _resolve_and_validate("https://attacker.example/x", strict=True)

        # Pin the validated IPs (as make_http_request does internally).
        _pinned_dns.pins = {host: list(addrs)}
        try:
            # Rebind attack: the next system getaddrinfo would return a
            # private IP. With the pin installed, getaddrinfo must return
            # the pinned public IP — not the rebound private IP.
            with patch("core.utils.http_client._client._orig_getaddrinfo", return_value=self._addrinfo("10.0.0.1")):
                resolved = socket.getaddrinfo(host, 443)
            ips = [info[4][0] for info in resolved]
            self.assertIn("8.8.8.8", ips, "pinned public IP should be used")
            self.assertNotIn("10.0.0.1", ips, "rebound private IP must not appear")
        finally:
            del _pinned_dns.pins

    @override_settings(SSRF_BLOCK_PRIVATE_IPS=True)
    def test_resolve_and_validate_rejects_private_ip(self) -> None:
        with patch("core.utils.http_client._client.socket.getaddrinfo", return_value=self._addrinfo("10.0.0.1")):
            with self.assertRaises(BaseCustomError) as ctx:
                _resolve_and_validate("https://internal.example/x", strict=True)
        self.assertIn("non-public", str(ctx.exception))

    @override_settings(SSRF_BLOCK_PRIVATE_IPS=False)
    def test_pin_skipped_when_ssrf_disabled(self) -> None:
        host, addrs = _resolve_and_validate("https://anywhere.example/x", strict=True)
        self.assertIsNone(host)
        self.assertEqual(addrs, [])

    def test_unpatched_orig_getaddrinfo_is_real(self) -> None:
        """The saved _orig_getaddrinfo is the system resolver, not the patched
        wrapper — needed so the pin can delegate to real DNS for un-pinned hosts."""
        self.assertFalse(getattr(_orig_getaddrinfo, "_ssrf_pinned", False))
