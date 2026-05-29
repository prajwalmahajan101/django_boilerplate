"""Producer-side enqueue helper.

Thin wrapper over ``Celery.send_task`` so call sites read like
``enqueue("send_welcome_email", user_id=42)`` instead of importing the
Celery app and threading the queue name through every call.

Resolves the active Celery app via :data:`celery.current_app` — a proxy
that returns whichever ``Celery(...)`` instance was last constructed
and set as default. ``config/celery.py`` constructs that instance at
boot, so by the time any code path hits ``enqueue`` the proxy
resolves correctly. Going through ``current_app`` (instead of
importing ``config.celery``) keeps ``apps/core/`` free of any sibling
or ``config`` import — the layering invariant the boilerplate enforces
via ``pre-commit``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from celery import current_app
from django.conf import settings


def enqueue(
    task_name: str,
    *args: Any,
    queue: str | None = None,
    countdown: float | None = None,
    eta: datetime | None = None,
    **kwargs: Any,
):
    """Send ``task_name`` to the configured Celery broker.

    Args:
        task_name: Fully qualified task name (matches what
            :func:`register_task` recorded).
        *args, **kwargs: Forwarded to the task body.
        queue: Override the default queue. Defaults to
            ``settings.CELERY_TASK_DEFAULT_QUEUE`` when set.
        countdown: Delay in seconds before the worker picks it up.
        eta: Absolute time at which to run the task (UTC).

    Returns:
        ``celery.result.AsyncResult`` — handle for the queued job.
    """
    queue_name = queue or getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", None)
    return current_app.send_task(
        task_name,
        args=args,
        kwargs=kwargs,
        queue=queue_name,
        countdown=countdown,
        eta=eta,
    )


__all__ = ["enqueue"]
