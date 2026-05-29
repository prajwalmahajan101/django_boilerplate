"""Dispatch primitives — best-effort and (future) durable lanes.

Today: ``FireAndForgetQueue`` only — a bounded in-process queue for
fire-and-forget work where dropping under load is preferable to blocking
the request path.

Deferred: durable task outbox (Postgres-backed table + drainer). The plan
defers the outbox because the only candidate consumer (remark email) is
being deprecated. Bring the outbox in when a real durable-dispatch need
arrives (partner webhook callbacks that must survive an outage, etc.).

Decision table — when to use which lane:

| Need | Use |
|---|---|
| Audit log entry the request shouldn't wait for | ``FireAndForgetQueue`` |
| Email that's nice-to-have but not part of the SLA | ``FireAndForgetQueue`` |
| Must-not-lose payment event | Build outbox first |
| Webhook callback with retry SLA | Build outbox first |
"""

from core.dispatch.fire_and_forget import (  # noqa: F401
    FireAndForgetQueue,
    drain_all,
    get_queue,
    registered_queues,
)
