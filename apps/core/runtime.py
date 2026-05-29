"""Core runtime settings accessor.

Thin indirection over ``django.conf.settings`` so ``apps.core`` modules
can read configuration through a single, mockable entry point and so
the cross-repo vocabulary stays aligned with the FastAPI sibling
(``src.core.runtime``).

``django.conf.settings`` is already a thread-safe ``LazySettings``
proxy, so this module adds no caching layer of its own. The value of
the indirection is:

* ``require(key)`` — explicit prod-required key validator that raises
  ``ImproperlyConfigured`` instead of an ``AttributeError`` deep in the
  call stack.
* ``get_settings()`` — single import target for tests to monkeypatch.
* ``reset()`` — no-op kept for API parity with the FastAPI sibling.
"""

from __future__ import annotations

from typing import Any

from django.conf import LazySettings, settings as django_settings
from django.core.exceptions import ImproperlyConfigured


def get_settings() -> LazySettings:
    """Return the Django settings proxy."""
    return django_settings


def require(key: str) -> Any:
    """Return ``settings.<key>``; raise if missing in non-DEBUG.

    Falls back to returning the value (which may be ``None``) under
    ``DEBUG=True`` so local development keeps working even when an
    optional knob is unset.
    """
    value = getattr(django_settings, key, None)
    if value in (None, "") and not getattr(django_settings, "DEBUG", False):
        raise ImproperlyConfigured(
            f"Required setting {key!r} is missing or empty.",
        )
    return value


def reset() -> None:
    """No-op. API parity with ``src.core.runtime.reset``."""
    return None
