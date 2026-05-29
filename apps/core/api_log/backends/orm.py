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

from django.db import transaction

logger = logging.getLogger(__name__)


class OrmApiLogBackend:
    backend_name = "orm"

    def persist(self, row: dict) -> None:
        from core.api_log.models import ApiLog

        try:
            with transaction.atomic():
                ApiLog.objects.create(**row)
        except Exception:
            # Audit-only sink — failure must never raise into the
            # fire-and-forget worker (which would terminate the task
            # and the dropped-count signal would silently overshoot).
            logger.exception("api_log persist failed; row dropped")
