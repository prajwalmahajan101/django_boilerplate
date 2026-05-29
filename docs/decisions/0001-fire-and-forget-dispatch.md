# ADR-0001: Use a bounded in-process queue for fire-and-forget side effects

- **Status:** Accepted
- **Date:** 2026-05-29
- **Deciders:** platform team

## Context

Several side effects (audit logs, telemetry, post-write notifications)
should not block the request path. They are best-effort by
construction — if the process dies before they flush, dropping them is
preferable to slowing the user. But running them inline still costs
request latency, and running them via Celery introduces a broker
round-trip plus a separate failure domain for every non-critical
write.

The runtime is gthread Gunicorn (multiple threads per worker process,
shared memory). We need a dispatch mechanism that:

1. Accepts work synchronously on the request thread without blocking
   on the side-effect's I/O.
2. Drops on overflow rather than queueing unboundedly (an audit
   storm must not exhaust memory).
3. Surfaces saturation loudly enough that operators notice before the
   drop rate crosses what the business considers tolerable.
4. Drains cleanly on worker shutdown so a graceful SIGTERM does not
   lose in-flight work.

## Decision

We use `apps.core.dispatch.fire_and_forget.FireAndForgetQueue` — a
named, bounded, in-process work queue backed by a `ThreadPoolExecutor`
and a `queue.Queue`. Each use case (audit, telemetry, …) registers its
own named queue with independent capacity bounds. Overflow drops the
item, increments a monotonically increasing drop counter, and emits a
`WARNING` log. Worker shutdown calls `drain_all(deadline)` so in-flight
items are flushed up to a configurable wall-clock budget.

External durable side effects (payment captures, SMS, anything where
loss is unacceptable) **do not** use this path — they go through
Celery and inherit the broker's at-least-once guarantees.

## Consequences

### Positive

- Zero broker latency in the request path for non-critical side
  effects.
- One mental model for every "best-effort" dispatch in the codebase.
- Saturation is observable (drop counter + WARNING) without per-call
  instrumentation.

### Negative

- Side effects are lost on hard kill (`SIGKILL`, OOM). This is
  acceptable by construction for the workloads on this path; anything
  that cannot tolerate loss must use Celery.
- The shared queue is bounded per-process, so a single misbehaving
  caller can starve every other caller on the same worker. Named
  queues isolate the blast radius but only when the caller chooses a
  distinct name.

### Neutral

- The queue lives in the worker process — there is no cross-process
  ordering guarantee. Consumers (e.g. an `api_logs` reader) must not
  assume monotonic ordering across requests handled by different
  workers.
- Replacing the in-process queue with a persistent backend later (Redis
  Streams, Kafka) is a drop-in swap because the public API is just
  `FireAndForgetQueue.submit(callable)`.

## Alternatives considered

- **Celery for every side effect.** Rejected: broker round-trip cost
  on the request path is too high for hot endpoints, and the failure
  modes (worker DLQ, retries) are overkill for genuinely best-effort
  work.
- **`asyncio.create_task` on a shared loop.** Rejected: Django views
  run sync under gthread; bringing async in just for dispatch would
  introduce a hybrid runtime with its own pitfalls (loop ownership,
  cancellation semantics).
- **Unbounded background thread + plain `Thread.start()`.** Rejected:
  no backpressure, no saturation signal, no shutdown semantics.

## References

- `apps/core/dispatch/fire_and_forget.py` — implementation.
- `apps/core/tests/test_fire_and_forget.py` — overflow + drain
  behaviour under load.
- `docs/audit-trail.md` — the largest consumer today.
- `docs/thread-safety.md` — the gthread invariants the queue honours.
