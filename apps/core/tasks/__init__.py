"""Celery task surface — registry + enqueue helpers.

Thin layer over Celery's :func:`celery.shared_task` decorator that:

* keeps a process-local registry of tasks defined through
  :func:`register_task`, so tests can assert wiring without poking at
  Celery internals; and
* exposes :func:`enqueue` so producer call sites read like
  ``enqueue("send_welcome_email", user_id=42)`` instead of plumbing
  the Celery app in by hand.

Establishes vocabulary parity with the FastAPI sibling
(``src.core.tasks``) so cross-repo developers see the same API.
"""

from core.tasks.queue import enqueue
from core.tasks.registry import register_task, registered_tasks

__all__ = ["enqueue", "register_task", "registered_tasks"]
