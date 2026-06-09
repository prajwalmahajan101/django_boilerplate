"""Unit tests for ``apps.core.api_log.sanitizers``."""

from __future__ import annotations

import json
from datetime import UTC

from core.api_log.sanitizers import (
    audit_safe,
    compute_ttl,
    redact_headers,
    serialize_body,
    truncate,
)
from django.test import SimpleTestCase, override_settings


class RedactHeadersTests(SimpleTestCase):
    def test_redacts_default_sensitive(self) -> None:
        out = redact_headers({"Authorization": "Bearer x", "X-Foo": "bar"})
        self.assertEqual(out["Authorization"], "[REDACTED]")
        self.assertEqual(out["X-Foo"], "bar")

    def test_case_insensitive(self) -> None:
        out = redact_headers({"authorization": "Bearer x"})
        self.assertEqual(out["authorization"], "[REDACTED]")

    @override_settings(API_LOG_SENSITIVE_HEADERS=["x-tenant"])
    def test_custom_header_list(self) -> None:
        out = redact_headers({"X-Tenant": "abc", "Authorization": "v"})
        self.assertEqual(out["X-Tenant"], "[REDACTED]")
        self.assertEqual(out["Authorization"], "v")


class TruncateTests(SimpleTestCase):
    def test_short_passes_through(self) -> None:
        self.assertEqual(truncate("abc", 10), "abc")

    def test_long_is_marked(self) -> None:
        out = truncate("x" * 50, 10)
        assert out is not None
        self.assertTrue(out.endswith("…[truncated]"))
        self.assertTrue(out.startswith("x" * 10))

    def test_none_passthrough(self) -> None:
        self.assertIsNone(truncate(None, 5))


class AuditSafeTests(SimpleTestCase):
    def test_bytes_become_size_summary(self) -> None:
        out = audit_safe(b"hello")
        self.assertEqual(out, {"__bytes__": True, "size_bytes": 5})

    def test_passthrough(self) -> None:
        self.assertEqual(audit_safe({"a": 1}), {"a": 1})


class SerializeBodyTests(SimpleTestCase):
    def test_string(self) -> None:
        self.assertEqual(serialize_body("hello"), "hello")

    def test_dict_becomes_json(self) -> None:
        out = serialize_body({"a": 1})
        assert out is not None
        self.assertEqual(json.loads(out), {"a": 1})

    def test_none(self) -> None:
        self.assertIsNone(serialize_body(None))

    def test_bytes_decoded(self) -> None:
        self.assertEqual(serialize_body(b"hello"), "hello")

    def test_dict_redacts_sensitive_keys(self) -> None:
        out = serialize_body({"username": "alice", "password": "p@ss", "api_key": "sk_live_x"})
        assert out is not None
        self.assertNotIn("p@ss", out)
        self.assertNotIn("sk_live_x", out)
        self.assertIn("alice", out)

    def test_json_string_body_redacted(self) -> None:
        out = serialize_body('{"token": "tk_abc", "name": "bob"}')
        assert out is not None
        self.assertNotIn("tk_abc", out)
        self.assertIn("bob", out)

    def test_json_bytes_body_redacted(self) -> None:
        out = serialize_body(b'{"authorization": "Bearer x", "id": 1}')
        assert out is not None
        self.assertNotIn("Bearer x", out)

    def test_nested_dict_redacted(self) -> None:
        out = serialize_body({"user": {"secret": "s", "name": "n"}})
        assert out is not None
        self.assertNotIn('"s"', out)


class ComputeTtlTests(SimpleTestCase):
    @override_settings(API_LOG_TTL_DAYS=0)
    def test_zero_returns_none(self) -> None:
        self.assertIsNone(compute_ttl())

    @override_settings(API_LOG_TTL_DAYS=7)
    def test_positive_returns_future_timestamp(self) -> None:
        ts = compute_ttl()
        assert ts is not None
        # Roughly 7 days from now (within a wide tolerance).
        from datetime import datetime

        delta = ts - int(datetime.now(UTC).timestamp())
        self.assertGreater(delta, 6 * 86_400)
        self.assertLess(delta, 8 * 86_400)
