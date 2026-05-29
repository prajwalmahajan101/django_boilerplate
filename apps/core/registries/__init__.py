"""Canonical namespace for the project's runtime extension registries.

Domain apps register their cross-cutting concerns from
``AppConfig.ready()`` via these helpers rather than editing peer-app
source. Two registries today:

- **RBAC** — ``register_resource(model_dotted_name, resource)`` maps
  ``"app_label.model_name"`` to a ``Resource`` enum value. Read by
  ``RBACBackend.has_perm`` / ``has_module_perms``.
- **Resilience** — ``register_resilience_service(name, config)``
  installs circuit-breaker + retry policy for a service name that
  ``@resilient("name")`` can then bind to.

The underlying implementations live next to their consumers
(``core.rbac_registry`` and ``core.resilience.registry``) for code-
locality reasons; this package is the canonical extension-point
surface that ``docs/adding-a-new-app.md`` references.

Usage::

    # apps/my_app/apps.py
    from django.apps import AppConfig
    from core.enums import Resource
    from core.registries import (
        register_resource,
        register_resilience_service,
    )


    class MyAppConfig(AppConfig):
        name = "my_app"

        def ready(self):
            register_resource("my_app.widget", Resource.WIDGET)
            register_resilience_service(
                "widget_api",
                {"circuit_breaker": {"fail_max": 5, "reset_timeout": 30}},
            )
"""

from __future__ import annotations

from core.rbac_registry import (
    app_resources,
    register_resource,
    registered_mappings,
    resource_for,
)
from core.resilience.registry import registry as resilience_registry

# Bound-method handle to match the verb/shape of ``register_resource``.
# Re-exported as a free function so callers don't import the singleton
# unless they specifically need its other methods.
register_resilience_service = resilience_registry.register_service

__all__ = [
    "register_resource",
    "resource_for",
    "app_resources",
    "registered_mappings",
    "register_resilience_service",
    "resilience_registry",
]
