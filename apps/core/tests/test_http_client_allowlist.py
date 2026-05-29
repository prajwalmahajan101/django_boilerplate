"""Tests for ``OUTBOUND_URL_ALLOWLIST`` enforcement in ``_assert_url_allowlisted``."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.base.exception import BaseCustomError
from core.utils.http_client import _assert_url_allowlisted, make_http_request


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
        with patch("core.utils.http_client._do_request") as do_request:
            do_request.return_value = object()
            result = make_http_request(
                method="GET",
                url="https://partner.example.com/api/x",
                trusted=True,
                max_attempts=1,
            )
        do_request.assert_called_once()
        self.assertIs(result, do_request.return_value)
