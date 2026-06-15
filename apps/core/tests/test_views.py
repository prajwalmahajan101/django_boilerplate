"""Tests for ``core.views`` (health / readiness / csp-report / metrics).

Drives each endpoint through the URL conf with DRF's
``APIRequestFactory`` so the ``@api_view`` / ``@throttle_classes`` /
``@never_cache`` decorator stack is exercised end-to-end. Health-probe
results are stubbed so we never depend on a live DB / Valkey / broker
at this tier — that's covered by ``test_healthcheck.py`` for the probe
internals and ``tests/e2e/`` for the wired path.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from core import views as core_views
from core.lifecycle.healthcheck import HealthCheckResult
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate


# ---------- helpers ------------------------------------------------------


def _call(view, request):
    """Invoke a @api_view function-based view and return the DRF response."""
    return view(request)


def _privileged_user():
    class U:
        is_authenticated = True
        has_superuser_role = True

    return U()


def _anon_user():
    class U:
        is_authenticated = False
        has_superuser_role = False

    return U()


def _stub_results(*pairs):
    """Build a ``run_checks`` return value from (name, healthy, detail) tuples."""
    results = [HealthCheckResult(name=n, healthy=h, detail=d) for n, h, d in pairs]
    return results, all(r.healthy for r in results)


# ---------- health_check -------------------------------------------------


def test_health_check_healthy_unprivileged_omits_detail():
    factory = APIRequestFactory()
    request = factory.get("/api/health/")
    request.user = _anon_user()
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(("database", True, "ok")),
    ):
        resp = _call(core_views.health_check, request)
    assert resp.status_code == 200
    assert resp.data == {"status": "healthy"}
    assert "checks" not in resp.data


def test_health_check_unhealthy_returns_503():
    factory = APIRequestFactory()
    request = factory.get("/api/health/")
    request.user = _anon_user()
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(("database", False, "down")),
    ):
        resp = _call(core_views.health_check, request)
    assert resp.status_code == 503
    assert resp.data["status"] == "unhealthy"


def test_health_check_privileged_attaches_check_detail():
    factory = APIRequestFactory()
    request = factory.get("/api/health/")
    force_authenticate(request, user=_privileged_user())
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(("database", True, "1ms")),
    ):
        resp = _call(core_views.health_check, request)
    assert resp.data["checks"] == {"database": "1ms"}


def test_health_check_privileged_short_status_for_unhealthy_db():
    """Unhealthy DB probe with no detail falls back to the _short() string."""
    factory = APIRequestFactory()
    request = factory.get("/api/health/")
    force_authenticate(request, user=_privileged_user())
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(("database", False, "")),
    ):
        resp = _call(core_views.health_check, request)
    assert resp.data["checks"] == {"database": "disconnected"}


def test_health_check_privileged_short_status_for_unhealthy_other():
    factory = APIRequestFactory()
    request = factory.get("/api/health/")
    force_authenticate(request, user=_privileged_user())
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(("cache", False, "")),
    ):
        resp = _call(core_views.health_check, request)
    assert resp.data["checks"] == {"cache": "unreachable"}


# ---------- readiness_check ----------------------------------------------


def test_readiness_check_ready_returns_200():
    factory = APIRequestFactory()
    request = factory.get("/api/readiness/")
    request.user = _anon_user()
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(
            ("database", True, "ok"),
            ("cache", True, "ok"),
            ("celery_broker", True, "ok"),
        ),
    ):
        resp = _call(core_views.readiness_check, request)
    assert resp.status_code == 200
    assert resp.data == {"status": "ready"}


def test_readiness_check_not_ready_returns_503():
    factory = APIRequestFactory()
    request = factory.get("/api/readiness/")
    request.user = _anon_user()
    with patch.object(
        core_views, "run_checks",
        return_value=_stub_results(
            ("database", True, "ok"),
            ("cache", False, "valkey down"),
            ("celery_broker", True, "ok"),
        ),
    ):
        resp = _call(core_views.readiness_check, request)
    assert resp.status_code == 503
    assert resp.data["status"] == "not_ready"


# ---------- csp_report ---------------------------------------------------


def test_csp_report_logs_sanitized_payload_and_returns_204(caplog):
    factory = APIRequestFactory()
    body = {
        "csp-report": {
            "violated-directive": "script-src 'self'",
            "effective-directive": "script-src",
            "disposition": "enforce",
            "status-code": 200,
            "document-uri": "https://attacker.example/leak",  # must be dropped
        }
    }
    request = factory.post(
        "/api/csp-report/",
        data=json.dumps(body),
        content_type="application/json",
    )
    request.user = _anon_user()
    with caplog.at_level("INFO", logger="core.views"):
        resp = _call(core_views.csp_report, request)
    assert resp.status_code == 204
    record = next(r for r in caplog.records if r.message == "csp_violation")
    # Only the bounded fields are forwarded.
    assert record.event == "csp_violation"
    assert record.violated_directive == "script-src 'self'"
    assert record.effective_directive == "script-src"
    assert record.disposition == "enforce"
    assert record.status_code == 200
    assert not hasattr(record, "document_uri")


def test_csp_report_accepts_flat_body_without_csp_report_wrapper():
    factory = APIRequestFactory()
    body = {"violated-directive": "style-src"}
    request = factory.post(
        "/api/csp-report/",
        data=json.dumps(body),
        content_type="application/json",
    )
    request.user = _anon_user()
    resp = _call(core_views.csp_report, request)
    assert resp.status_code == 204


def test_csp_report_tolerates_non_dict_body():
    factory = APIRequestFactory()
    request = factory.post(
        "/api/csp-report/",
        data=json.dumps(["not", "a", "dict"]),
        content_type="application/json",
    )
    request.user = _anon_user()
    resp = _call(core_views.csp_report, request)
    assert resp.status_code == 204


def test_csp_report_truncates_oversized_fields():
    factory = APIRequestFactory()
    body = {
        "csp-report": {
            "violated-directive": "x" * 500,
            "disposition": "y" * 500,
        }
    }
    request = factory.post(
        "/api/csp-report/",
        data=json.dumps(body),
        content_type="application/json",
    )
    request.user = _anon_user()
    with patch.object(core_views.logger, "info") as info:
        _call(core_views.csp_report, request)
    extra = info.call_args.kwargs["extra"]
    assert len(extra["violated_directive"]) == 200
    assert len(extra["disposition"]) == 50


# ---------- metrics_endpoint --------------------------------------------


def _metrics_request(remote_addr="127.0.0.1"):
    factory = APIRequestFactory()
    request = factory.get("/api/metrics")
    request.META["REMOTE_ADDR"] = remote_addr
    request.user = _anon_user()
    return request


@override_settings(METRICS_ALLOWED_IPS=["127.0.0.1"], METRICS_ENABLED=False)
def test_metrics_returns_503_when_disabled():
    resp = _call(core_views.metrics_endpoint, _metrics_request())
    assert resp.status_code == 503
    assert b"not configured" in resp.content


@override_settings(METRICS_ALLOWED_IPS=["10.0.0.0/8"], METRICS_ENABLED=False)
def test_metrics_403_when_client_ip_not_in_allow_list():
    resp = _call(core_views.metrics_endpoint, _metrics_request("8.8.8.8"))
    assert resp.status_code == 403
    assert b"IP-restricted" in resp.content


@override_settings(METRICS_ALLOWED_IPS=["10.0.0.0/8"], METRICS_ENABLED=False)
def test_metrics_cidr_match_admits_client_then_503_for_disabled():
    resp = _call(core_views.metrics_endpoint, _metrics_request("10.42.0.7"))
    assert resp.status_code == 503  # IP allowed, but disabled


@override_settings(METRICS_ALLOWED_IPS=["127.0.0.1"], METRICS_ENABLED=True)
def test_metrics_returns_503_when_enabled_but_library_missing():
    """METRICS_ENABLED=True without prometheus_client installed → 503."""
    # We can't easily uninstall prometheus_client mid-test; simulate the
    # ImportError via patching the import inside the view's lazy block.
    import builtins as _builtins

    orig_import = _builtins.__import__

    def _raise(name, *args, **kwargs):
        if name == "prometheus_client":
            raise ImportError("simulated")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_raise):
        resp = _call(core_views.metrics_endpoint, _metrics_request())
    assert resp.status_code == 503
    assert b"prometheus_client is not installed" in resp.content


# ---------- _ip_allowed --------------------------------------------------


@pytest.mark.parametrize(
    ("client_ip", "allow_list", "expected"),
    [
        ("127.0.0.1", ["127.0.0.1"], True),
        ("127.0.0.2", ["127.0.0.1"], False),
        ("10.0.0.5", ["10.0.0.0/8"], True),
        ("11.0.0.5", ["10.0.0.0/8"], False),
        ("", ["127.0.0.1"], False),
        ("not-an-ip", ["127.0.0.1"], False),
        ("127.0.0.1", ["bad-entry", "127.0.0.1"], True),
        ("127.0.0.1", ["bad-cidr/", "127.0.0.1"], True),
    ],
)
def test_ip_allowed_table(client_ip, allow_list, expected):
    assert core_views._ip_allowed(client_ip, allow_list) is expected


def test_metrics_client_ip_returns_empty_when_remote_addr_missing():
    factory = APIRequestFactory()
    request = factory.get("/api/metrics")
    request.META.pop("REMOTE_ADDR", None)
    assert core_views._metrics_client_ip(request) == ""
