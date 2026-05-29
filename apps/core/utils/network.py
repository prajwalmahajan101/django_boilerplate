"""Request-side networking helpers shared across middleware and rate limiting.

Originally each consumer (``RequestLoggingMiddleware``, the social-account
adapter, and any throttle keying logic) carried its own ``client_ip``
copy with identical behaviour. Extracting it here makes the proxy-header
policy a single source of truth — when ``USE_X_FORWARDED_FOR`` flips on,
the same logic fires for audit logs, last-login IP, and rate limits, so
the three systems can never disagree on who the caller is.

Policy:

* When ``settings.USE_X_FORWARDED_FOR`` is truthy, trust the first hop of
  ``X-Forwarded-For``; fall back to ``X-Real-IP``; finally fall back to
  the direct socket peer.
* Otherwise return ``REMOTE_ADDR`` directly.
* The string ``"unknown"`` is returned when no peer is recorded. Callers
  (audit log, throttle buckets) treat it as a valid label rather than a
  sentinel — never blank, never ``None``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str:
    """Resolve the request's client IP, honouring ``USE_X_FORWARDED_FOR``.

    Never raises. See module docstring for the trust policy.
    """
    if getattr(settings, "USE_X_FORWARDED_FOR", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        real_ip = request.META.get("HTTP_X_REAL_IP")
        if real_ip:
            return real_ip.strip()
    return request.META.get("REMOTE_ADDR") or "unknown"


__all__ = ["client_ip"]
