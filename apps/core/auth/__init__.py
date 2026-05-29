"""Pluggable DRF authentication registry.

Provides a named, settings-ordered chain of :class:`AuthProvider`
implementations behind a single DRF ``BaseAuthentication`` class
(:class:`CompositeAuthentication`). The shape mirrors the FastAPI
sibling so cross-repo developers see the same vocabulary; DRF's
existing per-class semantics (return ``None`` to skip / raise
``AuthenticationFailed`` to stop) are preserved without change.
"""

from core.auth.base import AuthProvider
from core.auth.composite import CompositeAuthentication
from core.auth.registry import (
    enabled_providers,
    register,
    registered_names,
    unregister,
)

__all__ = [
    "AuthProvider",
    "CompositeAuthentication",
    "enabled_providers",
    "register",
    "registered_names",
    "unregister",
]
