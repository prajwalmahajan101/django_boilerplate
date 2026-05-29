"""Django-ORM backend for ``api_logs``.

Executes ``ApiLog.objects.create(**row)`` off the request thread (via
the fire-and-forget queue). Wrap the call in ``transaction.atomic``
so the row either lands or doesn't — the queue retries nothing.

This replaces the async-batched psycopg writer in the FastAPI version.
Django's ORM is synchronous, the FireAndForgetQueue already provides
back-pressure + drain semantics, and the per-row overhead is fine for
the audit workload.
"""

from __future__ import annotations

import logging

from core.db import best_effort_atomic

logger = logging.getLogger(__name__)


class OrmApiLogBackend:
    backend_name = "orm"

    def persist(self, row: dict) -> None:
        from core.api_log.models import ApiLog

        # Audit-only sink — failure must never raise into the
        # fire-and-forget worker (which would terminate the task and
        # the dropped-count signal would silently overshoot).
        with best_effort_atomic("persist api_log row", logger=logger):
            ApiLog.objects.create(**row)
