"""Composable health / readiness probe primitives.

Callers compose a list of :data:`Check` callables and pass them to
:func:`run_checks`, which returns the aggregated result. Pre-built
probes for DB, cache, and Celery broker live in this module and are
the same ones used by :func:`core.views.health_check` /
:func:`core.views.readiness_check`.

A *health* endpoint typically answers "is the process alive?" (DB
only). A *readiness* endpoint answers "should the load balancer route
traffic here?" (DB + cache + broker + any external dependency).

This module is a Django/sync port of
``fastapi_boilerplate/src/core/lifecycle/healthcheck.py``. The
``async`` ``Check`` and ``APIRouter`` factories from that file are
collapsed to plain callables + a single aggregator because Django's
DRF view layer already provides the routing/response shape.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthCheckResult:
    """Outcome of one health/readiness probe.

    ``detail`` is short (one line) and safe to surface to privileged
    callers; unprivileged readiness responses omit it.
    """

    name: str
    healthy: bool
    detail: str = ""


# A probe is any zero-arg callable returning a result. Failures should
# be folded into ``HealthCheckResult(healthy=False, detail=...)`` rather
# than raising — :func:`run_checks` catches stray exceptions defensively
# but a probe that swallows its own error reports more cleanly.
Check = Callable[[], HealthCheckResult]


def run_checks(checks: list[Check]) -> tuple[list[HealthCheckResult], bool]:
    """Execute every probe sequentially and aggregate the verdict.

    Returns:
        (results, healthy) — ``healthy`` is ``True`` only when every
        probe returned healthy, or when ``checks`` is empty.
    """
    results: list[HealthCheckResult] = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:
            logger.exception("Health check %s raised", getattr(check, "__name__", "?"))
            results.append(
                HealthCheckResult(
                    name=getattr(check, "__name__", "check"),
                    healthy=False,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    healthy = all(r.healthy for r in results) if results else True
    return results, healthy


# ── Pre-built probes ───────────────────────────────────────────────────


def db_check() -> HealthCheckResult:
    """Probe the application database with ``SELECT 1``."""
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return HealthCheckResult(name="database", healthy=True, detail="connected")
    except Exception as exc:
        return HealthCheckResult(
            name="database",
            healthy=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


def cache_check(alias: str = "default") -> HealthCheckResult:
    """Round-trip a sentinel value through the named Django cache alias.

    On success also drives ``attempt_recover_all()`` so any backend
    currently in BOOT_FALLBACK (built before Valkey was reachable) can
    be rebuilt — that state cannot recover via the in-call resilience
    probe alone, and the readiness probe is the documented trigger.
    """
    try:
        from django.core.cache import caches

        cache = caches[alias]
        cache.set("_health_check", "ok", timeout=5)
        if cache.get("_health_check") != "ok":
            return HealthCheckResult(
                name=f"cache[{alias}]", healthy=False, detail="round-trip failed"
            )
        try:
            from resilience_kit.recovery import attempt_recover_all

            recovered = attempt_recover_all()
            detail = f"connected (recovered={recovered})" if recovered else "connected"
        except Exception:
            logger.exception("cache recovery dispatch failed")
            detail = "connected"
        return HealthCheckResult(name=f"cache[{alias}]", healthy=True, detail=detail)
    except Exception as exc:
        return HealthCheckResult(
            name=f"cache[{alias}]",
            healthy=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


def celery_broker_check() -> HealthCheckResult:
    """Open a short-lived connection to the Celery broker.

    Resolved via :data:`celery.current_app` rather than importing
    ``config.celery`` directly — keeps ``apps.core`` independent of
    the project skeleton (the layering guard in
    ``scripts/check_layering.py`` would otherwise flag this).
    """
    try:
        from celery import current_app as celery_app

        conn = celery_app.connection()
        try:
            conn.ensure_connection(max_retries=1, timeout=3)
        finally:
            conn.close()
        return HealthCheckResult(name="celery_broker", healthy=True, detail="connected")
    except Exception as exc:
        return HealthCheckResult(
            name="celery_broker",
            healthy=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


__all__ = [
    "Check",
    "HealthCheckResult",
    "cache_check",
    "celery_broker_check",
    "db_check",
    "run_checks",
]
