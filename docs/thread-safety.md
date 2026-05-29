# Thread-safety contract

Gunicorn runs with `--worker-class gthread --workers N --threads M` (configurable via `GUNICORN_WORKERS` / `GUNICORN_THREADS`, both default `4`). Multiple requests run concurrently **inside the same worker process**, so any module-level mutable state in the request path must be thread-safe.

> **Convention source of truth:** [../apps/core/CLAUDE.md](../apps/core/CLAUDE.md) · **Architecture context:** [architecture.md](architecture.md)

## Why it matters

With the classic `sync` Gunicorn worker class, a worker served one request at a time — module globals were effectively single-threaded per process, and race conditions only existed across processes. Switching to `gthread` adds intra-process concurrency. Anything cached at import time (HTTP sessions, boto3 clients, crypto primitives, compiled regexes, registries) now has to survive concurrent access from several OS threads.

The request path's shared singletons are all already thread-safe. The table below documents how — **new code must match one of these patterns or add a documented reason not to.**

## Contract — current shared state and its locking pattern

| Shared state | Pattern | Location |
|---|---|---|
| HTTP `requests.Session` | `threading.local()` — one `Session` per thread | `apps/core/utils/http_client.py::_thread_local.session` |
| boto3 clients (SES, Secrets Manager, S3) | `threading.local()` keyed by `(service, region)` | `apps/core/utils/aws.py::get_aws_client` |
| DRF per-request filter / permission caches | `ClassVar` + `threading.Lock` for first-init | several `*View` classes |
| Fernet key derivation | `functools.lru_cache(maxsize=1)` — thread-safe by contract | `apps/core/base/fields.py::_get_fernet` |
| Exception status-code map | Double-checked locking, invalidation on write | `apps/core/exceptions/handler.py::register_exception_mapping` |
| SQLAlchemy engine cache | `threading.Lock` around the dict | `apps/core/utils/db.py::_engine_cache` |
| Resilience circuit-breaker registry | `threading.Lock` | `apps/core/resilience/*` |

## Rules for new code

1. **Never** store request-scoped data at module level. Use `contextvars` if the value must cross an async boundary; otherwise pass it explicitly.
2. **Never** share Django ORM connections explicitly between threads. Django's connection handling already manages per-thread connections. Let it be.
3. If you cache anything at class or module scope, wrap initialisation in a `threading.Lock` or use `functools.lru_cache`.
4. If a utility holds stateful mutable configuration (lazy-frozen registries, config adapters, …), invalidation on write MUST be paired with the write API — see the exception-status-code map for the canonical pattern.
5. When in doubt, prefer `threading.local()` for "one per thread" resources over `threading.Lock()` around shared state.

## Gotchas

- `requests.Session` is **not** thread-safe. The thread-local pattern in `http_client.py` keeps each thread on its own `Session`. Do not replace with a shared module-level Session even if it looks simpler.
- boto3 clients are documented as thread-safe, but their credential-refresh behaviour is per-client. Sharing a client across threads works; sharing mutable session-level config (e.g. region per request) does not.
- `lru_cache` is thread-safe for cached reads but NOT for cache invalidation mid-flight. For keys that must be invalidated (partner bearer tokens on auth-field change), use an explicit cache with a lock — not `lru_cache`.
- Django's per-request permission cache (the `_permission_cache` in `HasResourcePermission`) lives on the **request object**, not at module scope. Each request's cache is isolated by construction — no locking needed.

## Related docs

- [architecture.md](architecture.md) — overall request lifecycle and where the middleware stack runs.
- [resilience.md](resilience.md) — circuit-breaker state is shared in Valkey across workers; in-process fallback uses `pybreaker` which is not cross-worker.
- [../apps/core/CLAUDE.md](../apps/core/CLAUDE.md) — short form of this contract for quick agent reference.
