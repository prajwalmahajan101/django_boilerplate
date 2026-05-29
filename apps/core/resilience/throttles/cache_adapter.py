"""Bridge a ``BaseCacheBackend`` to the Django cache API.

DRF's ``SimpleRateThrottle`` expects ``self.cache`` to expose Django's
positional-timeout cache API (``get / set / delete``), but our throttles
go through the cache provider, which speaks the ``BaseCacheBackend``
interface. This thin adapter is the only piece of glue between them.

Extracted from ``valkey_impl.py`` so the file there can focus on the
throttle classes themselves.
"""

from __future__ import annotations


class DjangoCacheAdapter:
    """Wraps a ``BaseCacheBackend`` to provide the Django cache API."""

    def __init__(self, backend):
        self._backend = backend

    def get(self, key, default=None):
        result = self._backend.get(key)
        return result if result is not None else default

    def set(self, key, value, timeout=None):
        self._backend.set(key, value, timeout=timeout)

    def delete(self, key):
        self._backend.delete(key)
