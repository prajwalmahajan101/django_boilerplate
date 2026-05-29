"""Per-service resilience configuration registry.

Manages circuit breakers and retry configs per service. Uses the circuit
breaker provider (Valkey default, pybreaker fallback) for breaker creation.
"""

import copy
import importlib
from threading import Lock

from django.conf import settings

from core.resilience.circuit_breaker.base import BaseCircuitBreaker, CircuitBreakerConfig
from core.resilience.circuit_breaker.provider import get_registry


class ResilienceRegistry:
    """Registry that manages circuit breakers and retry configs per service.

    Usage::

        from core.resilience.registry import registry

        # At service module level or in AppConfig.ready()
        registry.register_service("payment_gateway", {
            "circuit_breaker": {"fail_max": 3, "reset_timeout": 60},
            "retry": {"max_attempts": 5},
        })
    """

    def __init__(self):
        self._breakers: dict[str, BaseCircuitBreaker] = {}
        self._services: dict[str, dict] = {}
        self._lock = Lock()

    @staticmethod
    def _resolve_class(dotted_path: str) -> type:
        """Resolve a dotted path string to a class."""
        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def register_service(self, service_name: str, config: dict) -> None:
        """Register resilience overrides for a service."""
        if service_name in self._breakers:
            raise ValueError(
                f"Cannot register '{service_name}': a circuit breaker "
                "has already been created for this service. "
                "Register services before the first call."
            )
        self._services[service_name] = config

    def get_config(self, service_name: str) -> dict:
        defaults = copy.deepcopy(settings.RESILIENCE_DEFAULTS)
        overrides = self._services.get(service_name, {})
        for section in ("circuit_breaker", "retry"):
            if section in overrides:
                defaults[section].update(overrides[section])

        # Resolve string references in retry_on to actual exception classes
        retry_on = defaults["retry"].get("retry_on", ())
        if retry_on and isinstance(retry_on[0], str):
            defaults["retry"]["retry_on"] = tuple(
                self._resolve_class(cls_path) for cls_path in retry_on
            )

        return defaults

    def get_breaker(self, service_name: str) -> BaseCircuitBreaker:
        """Get or create a circuit breaker for the named service.

        Uses the circuit breaker provider (Valkey → pybreaker fallback).
        Config is read from RESILIENCE_DEFAULTS merged with per-service overrides.
        """
        breaker = self._breakers.get(service_name)
        if breaker is not None:
            return breaker

        with self._lock:
            # Double-check under lock
            if service_name not in self._breakers:
                cb_config = self.get_config(service_name)["circuit_breaker"]
                excluded = cb_config.get("excluded_exceptions", ())
                if excluded and isinstance(excluded[0], str):
                    excluded = tuple(self._resolve_class(cls_path) for cls_path in excluded)
                config = CircuitBreakerConfig(
                    failure_threshold=cb_config.get("fail_max", 5),
                    recovery_timeout=cb_config.get("reset_timeout", 30),
                    success_threshold=cb_config.get("success_threshold", 2),
                    excluded_exceptions=tuple(excluded),
                )
                cb_registry = get_registry()
                self._breakers[service_name] = cb_registry.get_or_create(
                    service_name, config
                )
            return self._breakers[service_name]


registry = ResilienceRegistry()
