"""Health check, readiness, and metrics endpoints."""

import ipaddress
import logging
from typing import Any

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from core.api_schemas import health_schema, readiness_schema
from core.lifecycle.healthcheck import (
    HealthCheckResult,
    cache_check,
    celery_broker_check,
    db_check,
    run_checks,
)
from resilience_kit.adapters.django.drf_throttles import BurstThrottle

logger = logging.getLogger(__name__)


def _is_privileged(request: Request) -> bool:
    return hasattr(request, "user") and getattr(
        request.user, "has_superuser_role", False
    )


def _short(result: HealthCheckResult) -> str:
    """Short status string for the unprivileged checks dict."""
    if result.healthy:
        return "connected"
    return "disconnected" if "database" in result.name else "unreachable"


def _attach_checks(
    payload: dict[str, Any],
    results: list[HealthCheckResult],
    privileged: bool,
) -> None:
    if privileged:
        payload["checks"] = {r.name: r.detail or _short(r) for r in results}


@health_schema
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
@never_cache
def health_check(request: Request) -> Response:
    """Health check endpoint for load balancers and monitoring.

    Composes :func:`core.lifecycle.healthcheck.db_check`. The privileged
    response surfaces per-check detail; the unprivileged response is a
    single ``status`` field.
    """
    results, healthy = run_checks([db_check])
    payload: dict[str, Any] = {"status": "healthy" if healthy else "unhealthy"}
    _attach_checks(payload, results, _is_privileged(request))
    return Response(payload, status=200 if healthy else 503)


@readiness_schema
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
@never_cache
def readiness_check(request: Request) -> Response:
    """Readiness check for Kubernetes/orchestration systems.

    Composes DB + cache + Celery-broker probes from
    :mod:`core.lifecycle.healthcheck`. Cache probe drives
    ``attempt_recover_all()`` on success so any BOOT_FALLBACK backend is
    rebuilt — that state cannot recover via the in-call resilience
    probe and the readiness endpoint is the documented trigger.
    """
    results, healthy = run_checks([db_check, cache_check, celery_broker_check])
    payload: dict[str, Any] = {"status": "ready" if healthy else "not_ready"}
    _attach_checks(payload, results, _is_privileged(request))
    return Response(payload, status=200 if healthy else 503)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([BurstThrottle])
@never_cache
def csp_report(request: Request) -> Response:
    """Receive Content-Security-Policy violation reports.

    Browsers POST a CSP violation here when an inline script / connect /
    style request fails the policy. We log a sanitized record at INFO so
    log aggregation can spot policy drift without exposing user-controlled
    URLs in error logs.

    No auth — browsers can't carry credentials on this endpoint. DRF's
    ``BurstThrottle`` is the defence-in-depth cap alongside any nginx
    rate-limit, so a single browser stuck in a CSP-violation loop (or a
    misconfigured nginx) cannot drive unbounded log volume.
    """
    body = request.data if isinstance(request.data, dict) else {}
    report = body.get("csp-report") if isinstance(body.get("csp-report"), dict) else body
    sanitized = {
        # Only the bounded, low-risk fields. Everything else (URLs,
        # document URIs, source files) is treated as untrusted noise.
        "violated_directive": str(report.get("violated-directive", ""))[:200],
        "effective_directive": str(report.get("effective-directive", ""))[:200],
        "disposition": str(report.get("disposition", ""))[:50],
        "status_code": report.get("status-code"),
    }
    logger.info("csp_violation", extra={"event": "csp_violation", **sanitized})
    return Response(status=204)


def _metrics_client_ip(request: Request) -> str:
    """Return the remote IP for ``/metrics`` ACL checks.

    Trusts ``REMOTE_ADDR`` only — Prometheus scrapers run inside the trust
    boundary, so ``X-Forwarded-For`` is intentionally NOT honoured here
    (a spoofed XFF header would otherwise bypass the allow-list).
    """
    return request.META.get("REMOTE_ADDR", "") or ""


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
@never_cache
def metrics_endpoint(request: Request) -> HttpResponse:
    """Prometheus scrape endpoint — wired but not yet exporting.

    The URL slot is reserved so future Prometheus scrapers + monitoring-stack
    provisioning have a stable target. Today the endpoint returns 503 with
    a documented body; activating Prometheus is a one-line ``pip install
    prometheus-client`` plus flipping ``METRICS_ENABLED=True`` (see
    ``docs/observability.md``).

    Access is gated by ``METRICS_ALLOWED_IPS`` (default ``['127.0.0.1']``).
    Source IPs outside the allow-list receive 403, not 503 — the difference
    matters to a misconfigured scraper trying to diagnose its own failure.
    """
    allowed = list(getattr(settings, "METRICS_ALLOWED_IPS", ["127.0.0.1"]))
    client_ip = _metrics_client_ip(request)
    if not _ip_allowed(client_ip, allowed):
        return HttpResponse(
            "forbidden: metrics endpoint is IP-restricted",
            status=403,
            content_type="text/plain; charset=utf-8",
        )

    if not getattr(settings, "METRICS_ENABLED", False):
        return HttpResponse(
            "metrics exporter not configured",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    # When METRICS_ENABLED flips True, this branch will lazy-import
    # prometheus_client and stream `generate_latest()`. Today the
    # combination (flag on, library absent) is an explicit misconfig.
    try:
        from prometheus_client import (  # type: ignore[import-not-found]  # noqa: PLC0415
            CONTENT_TYPE_LATEST,
            generate_latest,
        )
    except ImportError:
        return HttpResponse(
            "metrics enabled but prometheus_client is not installed",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)


def _ip_allowed(client_ip: str, allow_list: list[str]) -> bool:
    """Return True when ``client_ip`` falls inside any allow-list entry.

    Allow-list entries may be plain IPs (``127.0.0.1``) or CIDR blocks
    (``10.0.0.0/8``). An empty client IP never matches.
    """
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in allow_list:
        try:
            if "/" in entry:
                if ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False
