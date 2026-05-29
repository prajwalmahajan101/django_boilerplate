"""Resource ↔ Model registry for RBAC.

Domain apps populate this registry from their ``AppConfig.ready()`` so
adding a new app does not require editing the auth backend. Every app
registers its own ``Resource`` mappings via ``register_resource()`` and
the backend reads them through ``resource_for()``; new domain apps drop
in next to ``accounts/`` without any cross-app source edit.

Two read APIs:

* ``resource_for(app_label, model_name)`` — used inside the RBAC backend.
* ``app_resources(app_label)`` — used by the admin-sidebar permission
  check (``has_module_perms``).

Writes use ``register_resource(model_dotted_name, resource)`` where the
key is ``"<app_label>.<model_name>"`` (lower-case, matching Django's
``Permission.codename`` convention).
"""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_RESOURCE_FOR_MODEL: dict[str, str] = {}


def register_resource(model_dotted_name: str, resource: str) -> None:
    """Register a ``"app_label.model_name"`` -> ``Resource`` mapping.

    Idempotent: re-registering the same mapping is a no-op. Re-registering
    the same key with a different resource raises ``ValueError`` because
    a model can only own one RBAC resource — silent overwrites would
    cause subtle permission drift.
    """
    key = model_dotted_name.lower()
    with _lock:
        existing = _RESOURCE_FOR_MODEL.get(key)
        if existing is None:
            _RESOURCE_FOR_MODEL[key] = resource
            return
        if existing != resource:
            raise ValueError(
                f"register_resource({key!r}): already mapped to "
                f"{existing!r}, refusing to overwrite with {resource!r}."
            )


def resource_for(app_label: str, model_name: str) -> str | None:
    """Return the Resource registered for ``"<app_label>.<model_name>"``."""
    return _RESOURCE_FOR_MODEL.get(f"{app_label}.{model_name}".lower())


def app_resources(app_label: str) -> list[str]:
    """Return every Resource registered for any model in ``app_label``."""
    prefix = f"{app_label}.".lower()
    return [
        resource
        for key, resource in _RESOURCE_FOR_MODEL.items()
        if key.startswith(prefix)
    ]


def registered_mappings() -> dict[str, str]:
    """Return a shallow copy of the full mapping (for diagnostics / tests)."""
    return dict(_RESOURCE_FOR_MODEL)
