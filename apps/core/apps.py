import atexit

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.utils.db import dispose_all_engines

        atexit.register(dispose_all_engines)

        self._register_resilience_services()
        self._start_recovery_monitor()

    def _register_resilience_services(self) -> None:
        """Register one entry per outbound integration so the
        ``@resilient("name")`` decorator has a breaker + retry policy to
        bind to. Extend this method per-domain when you add a new
        external dependency.

        ``s3`` excludes ``S3NotFoundError`` so cache-miss probes don't
        trip the breaker — only genuine outages (timeouts, 5xx,
        connection errors) count.
        """
        from core.resilience.registry import registry

        try:
            registry.register_service(
                "s3",
                {
                    "circuit_breaker": {
                        "fail_max": 5,
                        "reset_timeout": 30,
                        "excluded_exceptions": (
                            "core.exceptions.infrastructure.S3NotFoundError",
                        ),
                    },
                },
            )
        except ValueError:
            pass

    def _start_recovery_monitor(self) -> None:
        """Single recovery monitor thread per process.

        Guarded by an idempotent ``start()`` so autoreload / repeated
        ready() / test fixtures don't accumulate threads.
        """
        try:
            from core.resilience.recovery import monitor

            monitor.start()
            atexit.register(monitor.stop)
        except Exception:  # noqa: BLE001 — never fail app boot
            import logging

            logging.getLogger(__name__).exception(
                "failed to start ValkeyRecoveryMonitor — recovery disabled"
            )
