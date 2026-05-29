# Scalability

> Companion to [resilience.md](resilience.md) (failure-mode behaviour),
> [thread-safety.md](thread-safety.md) (concurrency contract), and
> [configuration.md](configuration.md) (pool-sizing env vars).

This page covers capacity planning: pool sizing math, Valkey failure modes,
worker concurrency, and the levers available before horizontal scaling.

## 1. Gunicorn worker × thread sizing

The boilerplate uses `gthread` workers — each worker is a process with N
threads sharing the GIL. Sizing:

```
total concurrent requests = GUNICORN_WORKERS * GUNICORN_THREADS
```

Recommended starting points:

| Variable | Local | UAT | Prod | Notes |
|---|---|---|---|---|
| `GUNICORN_WORKERS` | 2 | 4 | 2× vCPU | One process per vCPU is the usual ceiling before context-switching dominates. |
| `GUNICORN_THREADS` | 2 | 4 | 4–8 | Higher only if requests are I/O-bound and the DB pool can keep up. |

Raising `GUNICORN_THREADS` is the cheapest way to absorb I/O-bound load —
each thread parks on a socket while another services the next request. The
ceiling is set by downstream pools (see §2), not by the GIL.

## 2. Database connection pool

Every Gunicorn thread can hold a database connection open at once. The pool
must cover the worst case:

```
db_pool_size >= GUNICORN_WORKERS * GUNICORN_THREADS / oversubscribe_factor
```

`oversubscribe_factor` is the ratio of threads that are blocked on something
other than the DB at any moment (external HTTP, cache, CPU). Empirically
`1.2`–`1.5` is safe for typical web workloads.

| Layer | Setting | Where |
|---|---|---|
| Django connection cache | `CONN_MAX_AGE` | `config/settings/base.py::DATABASES` |
| Engine-level pool (for SQLAlchemy ad-hoc queries) | `*_DB_POOL_SIZE`, `*_DB_MAX_OVERFLOW` | per-service env vars; consumed by `core/utils/db.py::get_engine` |
| Postgres server | `max_connections` | server-side |

Sum every client's pool: `web pool + worker pool + beat pool + ad-hoc tools`
must stay under `max_connections` with headroom for psql / migrations.

## 3. Celery worker concurrency

See [celery-topology.md](celery-topology.md). Sizing rules:

- **CPU-bound tasks** — concurrency ≈ vCPU count. Beyond that, throughput
  plateaus and latency climbs.
- **I/O-bound tasks (external HTTP, SES, S3)** — concurrency is limited by
  the external service's quota, not local CPU. Pin
  `CELERY_WORKER_CONCURRENCY` explicitly so a runaway worker doesn't trip a
  rate limit and cause a circuit breaker storm.
- **Mixed workload** — run two worker pools (CPU and I/O) on different
  queues rather than tuning a single pool for both.

## 4. Valkey failure modes

[resilience.md](resilience.md) is the authority on per-subsystem fallback.
Summary:

| Subsystem | Fail-open path | Recovery |
|---|---|---|
| Cache | in-memory backend | in-call recovery check (throttled) + readiness probe |
| Circuit breaker storage | pybreaker (in-process) | `reset_breaker_registry` rebuilds against current Valkey |
| Rate-limit throttles | DRF in-memory throttles | `reset_throttle_backend` re-resolves classes |
| Celery broker | **fail-CLOSED** | `.delay()` raises — wrap critical paths in an outbox table |

The principle is: **client-side degradation must not cascade into a
correctness bug.** Cache misses turn into DB hits, throttles fall back to
per-process counters, breakers fall back to in-memory state. Broker outages
are the exception — the broker is on the critical path for at-least-once
side effects.

## 5. Sentinel-aware client config

The client side is **ready** for a Valkey / Redis Sentinel cluster — both
`redis-py` and Celery accept a Sentinel transport. Activation: set
`VALKEY_SENTINEL_HOSTS` (comma-separated `host:port` pairs) and
`VALKEY_SENTINEL_MASTER_NAME`; the cache / broker URLs become
`sentinel://...` instead of `redis://...`. Standing up the Sentinel cluster
itself is out of scope for the boilerplate.

## 6. Scaling checklist

Before reaching for horizontal scaling, walk this list:

1. **Are slow queries the bottleneck?** Check `pg_stat_statements`. Add
   indexes / rewrite N+1 patterns before adding hardware.
2. **Are DB connections saturated?** Raise pool / `max_connections` first;
   horizontal web scaling without raising the pool just deadlocks.
3. **Is the cache hit rate healthy?** A cold cache makes every request
   pessimistically slow. Warm critical caches on deploy.
4. **Is a single external service the limiter?** Look for `@resilient`
   breakers tripping in logs. Fix at the integration layer (caching,
   batching, fail-soft) before adding workers.
5. **Are workers idle?** Match worker count to actual queue depth, not to a
   hypothetical peak.

Horizontal scaling (multiple web / worker hosts) is a correctness concern —
revisit [thread-safety.md](thread-safety.md) for any module-level state that
assumed a single process.

## 7. Out of scope for the boilerplate

- Standing up Valkey / Redis Sentinel cluster.
- Standing up RDS read replicas / per-tenant sharding.
- Application-level load tests against staging / prod.
- CDN / edge caching topology.

These are project-specific and intentionally left to the consuming repo.

## 8. Tuning checklist (env vars)

Every knob below is read at boot from the environment; defaults match the
section §1 / §3 recommendations for a moderate-traffic deployment.

### Gunicorn

| Variable | Default | Local | UAT | Prod | Notes |
|---|---|---|---|---|---|
| `GUNICORN_WORKERS` | 4 | 2 | 4 | 2 × vCPU | One process per vCPU is the usual ceiling. |
| `GUNICORN_THREADS` | 4 | 2 | 4 | 4–8 | Higher only if I/O-bound and DB pool keeps up. |
| `GUNICORN_TIMEOUT` | 130 | — | — | — | Must exceed downstream-call timeouts. |
| `GUNICORN_MAX_REQUESTS` | 10000 | — | — | — | Recycles workers to bound memory growth. |
| `GUNICORN_MAX_REQUESTS_JITTER` | 500 | — | — | — | Avoid synchronous recycle storms. |
| `GUNICORN_BACKLOG` | 2048 | — | — | — | Raise if OS listen queue overflows. |

### Celery

| Variable | Default | Notes |
|---|---|---|
| `CELERY_TASK_TIME_LIMIT` | 1800 | Seconds before hard SIGKILL. |
| `CELERY_TASK_SOFT_TIME_LIMIT` | 1500 | Seconds before `SoftTimeLimitExceeded`. |
| `CELERY_WORKER_CONCURRENCY` | 4 | Threads per worker process. |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | 1 | Fair dispatch — keep at 1 for long tasks. |
| `CELERY_SEND_EVENTS` | true | Toggle to `false` in prod once metrics replace Flower. |

### Fire-and-forget queue load-shed

The bounded `FireAndForgetQueue` (`apps/core/dispatch/fire_and_forget.py`)
drops on overflow by default. High-volume callers should check
`is_saturated()` before `submit()` and surface a 503 via
`ServiceUnavailableError` instead of accepting silent drops:

```python
queue = get_queue("audit_log")
if queue.is_saturated():
    raise ServiceUnavailableError("audit_log queue is saturated; retry later")
queue.submit(lambda: write_audit_row(payload))
```

The threshold defaults to 0.9 of `max_in_flight`; tune via the constructor
argument when instantiating the queue.
