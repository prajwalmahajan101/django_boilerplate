"""Regression test for ISSUE-226 — CSP-report endpoint defence-in-depth.

The `csp_report` endpoint accepts unauthenticated POSTs and logs each
violation at INFO. Before ISSUE-226 it carried `throttle_classes=[]` and
relied entirely on nginx for rate-limiting. The rest of this codebase
pairs nginx with at least one DRF throttle on every unauthenticated
endpoint; this test pins that contract on csp_report.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from resilience_kit.adapters.django.drf_throttles import BurstThrottle
from core.views import csp_report


class CSPReportThrottleContractTests(SimpleTestCase):
    def test_csp_report_carries_burst_throttle(self) -> None:
        # `@api_view` wraps the function as a class-based view; the
        # `throttle_classes` attribute lives on `.cls`.
        throttle_classes = getattr(csp_report.cls, "throttle_classes", [])
        self.assertIn(
            BurstThrottle,
            throttle_classes,
            "csp_report must carry BurstThrottle (defence-in-depth alongside "
            "nginx rate-limit). See ISSUE-226.",
        )
