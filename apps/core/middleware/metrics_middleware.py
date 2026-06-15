"""HTTP request duration middleware — NOT wired today.

This skeleton lands so that the activation path is a single edit in
``config/settings/base.py`` (uncomment the entry in ``MIDDLEWARE``) once
``prometheus-client`` is added to ``requirements/prod.in``. Keeping the
class committed avoids the standard "design the middleware while the
exporter outage is in progress" anti-pattern.

The route label intentionally uses ``request.resolver_match.view_name``
rather than the raw path so URL parameters (IDs, slugs) don't blow up
cardinality. See ``docs/observability.md``.

Dormant: not on the request path today; ``config/settings/base.py``
``MIDDLEWARE`` deliberately does not list this class (see ``apps/core/CLAUDE.md``
§ "core/middleware/metrics_middleware.py"). Omitted from the coverage
gate. The dormant-import AST gate scheduled for M3 will fail the build if
``MIDDLEWARE`` (or any other production wiring) starts referencing it
without a matching integration test landing in the same change.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class MetricsMiddleware:
    """Measure end-to-end request duration and tee it into ``core.metrics``.

    Currently unused — ``MIDDLEWARE`` does not reference this class. The
    activation procedure is documented in ``docs/observability.md``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from core.metrics import record_duration

        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000

        status = "ok" if response.status_code < 500 else "error"
        record_duration(
            "http_request",
            duration_ms,
            status=status,
        )
        return response
