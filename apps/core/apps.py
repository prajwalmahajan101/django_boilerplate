import atexit
import contextlib

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Django app config for the shared ``core`` package."""

    name = "core"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.utils.db import (
            dispose_all_engines,  # allow-dormant-import: atexit cleanup hook; see core/utils/db.py docstring
        )

        atexit.register(dispose_all_engines)

        self._register_resilience_services()

    def _register_resilience_services(self) -> None:
        """Register one entry per outbound integration with the resilience kit.

        The ``@resilient("name")`` decorator binds to entries registered here
        for breaker + retry policy. Extend this method per-domain when you
        add a new external dependency.

        ``s3`` excludes ``S3NotFoundError`` so cache-miss probes don't
        trip the breaker — only genuine outages (timeouts, 5xx,
        connection errors) count.
        """
        from resilience_kit import registry

        with contextlib.suppress(ValueError):
            registry.register_service(
                "s3",
                {
                    "circuit_breaker": {
                        "fail_max": 5,
                        "reset_timeout": 30,
                        # S3NotFoundError is a boilerplate-domain subclass
                        # (S3-cache-miss is expected, not an outage).
                        "excluded_exceptions": ("core.exceptions.infrastructure.S3NotFoundError",),
                    },
                },
            )
