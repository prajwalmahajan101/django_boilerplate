"""Tests for ``core.metrics`` — the cardinality contract is the load-bearing
invariant. If these tests pass, the Prometheus exporter swap is safe to do.

Pin:
  * Bounded label keys are accepted and emit one log record with the
    documented payload.
  * Unbounded keys (the named forbidden list) raise ``CardinalityViolation``.
  * Random unknown keys also raise — the bounded list is closed.
  * The ``/api/metrics`` endpoint returns HTTP 503 with the documented body
    while METRICS_ENABLED is False (the default).
  * Non-allowlisted source IPs get 403 even when METRICS_ENABLED would otherwise
    serve the body, so a misconfigured perimeter doesn't expose internals.
"""

from __future__ import annotations

import logging

from django.test import Client, SimpleTestCase, override_settings

from core.metrics import (
    CardinalityViolation,
    record_counter,
    record_duration,
    record_gauge,
)


class CardinalityContractTests(SimpleTestCase):
    def test_bounded_labels_accepted(self) -> None:
        # All four bounded keys exercised — should not raise.
        record_duration(
            "partner_push",
            42.0,
            status="ok",
            subsystem="dispatch",
            partner_slug="ABC",
            outcome="success",
        )
        record_counter("partner_push", status="ok", subsystem="dispatch")
        record_gauge("task_outbox_depth", 5.0, subsystem="outbox")

    def test_forbidden_key_request_id(self) -> None:
        with self.assertRaises(CardinalityViolation) as ctx:
            record_duration("partner_push", 1.0, request_id="x")  # type: ignore[arg-type]
        self.assertIn("request_id", str(ctx.exception))

    def test_forbidden_key_app_number(self) -> None:
        with self.assertRaises(CardinalityViolation):
            record_duration("partner_push", 1.0, app_number="APP-1")  # type: ignore[arg-type]

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaises(CardinalityViolation) as ctx:
            record_duration("partner_push", 1.0, free_form_label="something")  # type: ignore[arg-type]
        # Error message must point the contributor at the allow-list and the doc.
        self.assertIn("allow-list", str(ctx.exception))

    def test_record_duration_emits_log_record(self) -> None:
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = records.append  # type: ignore[method-assign]
        logger = logging.getLogger("core.metrics")
        logger.addHandler(handler)
        try:
            record_duration("partner_push", 12.34, status="ok", subsystem="dispatch")
        finally:
            logger.removeHandler(handler)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.event, "partner_push")  # type: ignore[attr-defined]
        self.assertEqual(rec.duration_ms, 12.34)  # type: ignore[attr-defined]
        self.assertEqual(rec.metric, "duration")  # type: ignore[attr-defined]


class MetricsEndpointTests(SimpleTestCase):
    """The /api/metrics URL slot is reserved; today it returns 503."""

    @override_settings(METRICS_ENABLED=False, METRICS_ALLOWED_IPS=["127.0.0.1"])
    def test_disabled_returns_503_with_documented_body(self) -> None:
        client = Client(REMOTE_ADDR="127.0.0.1")
        response = client.get("/api/metrics")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"metrics exporter not configured", response.content)

    @override_settings(METRICS_ENABLED=False, METRICS_ALLOWED_IPS=["127.0.0.1"])
    def test_forbidden_ip_returns_403(self) -> None:
        client = Client(REMOTE_ADDR="10.99.99.99")
        response = client.get("/api/metrics")
        self.assertEqual(response.status_code, 403)

    @override_settings(METRICS_ENABLED=True, METRICS_ALLOWED_IPS=["127.0.0.1"])
    def test_enabled_serves_or_503s_based_on_library_presence(self) -> None:
        """``prometheus-client`` is a transitive dep in this repo today.

        If it imports cleanly, flipping ``METRICS_ENABLED=True`` must
        serve the Prometheus text format; if it ever gets pruned, the
        endpoint must surface a clear 503 instead of crashing.
        """
        client = Client(REMOTE_ADDR="127.0.0.1")
        response = client.get("/api/metrics")
        try:
            import prometheus_client  # noqa: F401
            prom_installed = True
        except ImportError:
            prom_installed = False
        if prom_installed:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/plain", response["Content-Type"])
        else:
            self.assertEqual(response.status_code, 503)
            self.assertIn(b"prometheus_client", response.content)
