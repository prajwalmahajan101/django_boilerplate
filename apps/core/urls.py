from django.urls import path

from core.views import csp_report, health_check, metrics_endpoint, readiness_check

app_name = "core"

urlpatterns = [
    path("health/", health_check),
    path("readiness/", readiness_check),
    # /metrics has no trailing slash — convention for Prometheus scrape
    # endpoints, so a scraper configured against the conventional path
    # works without per-target overrides. Returns 503 until METRICS_ENABLED
    # is flipped on; see docs/observability.md.
    path("metrics", metrics_endpoint, name="metrics"),
    # Browser-driven CSP violation report sink. Once nginx is in front
    # and serves Content-Security-Policy headers with `report-uri
    # /api/csp-report/` the endpoint will start receiving violations.
    path("csp-report/", csp_report, name="csp-report"),
]
