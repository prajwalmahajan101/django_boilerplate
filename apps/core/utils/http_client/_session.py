"""Thread-local ``requests.Session`` pool for the outbound HTTP client.

One session per thread keeps connection pooling honest under gthread
Gunicorn — each worker thread reuses its own TCP / TLS handshake
across calls but a session is never shared across threads (which the
``requests`` library does not guarantee is safe).
"""

from __future__ import annotations

import threading

import requests

_thread_local = threading.local()


def get_session() -> requests.Session:
    """Return the calling thread's ``requests.Session`` (lazy-create)."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


__all__ = ["get_session"]
