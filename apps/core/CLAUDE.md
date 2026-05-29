# core — Shared infrastructure

> **Architecture:** [../../docs/architecture.md](../../docs/architecture.md) · **Resilience deep-dive:** [../../docs/resilience.md](../../docs/resilience.md) · **Thread-safety contract:** [../../docs/thread-safety.md](../../docs/thread-safety.md) · **Observability:** [../../docs/development.md#observability](../../docs/development.md#observability)

Never mounted as a standalone feature. Shared infrastructure only. **Nothing in `core` imports from domain apps** (`accounts`, `partners`, `leads`, `queries`).

## What lives here

- `core/base/` — `BaseModel`, `NamedBaseModel`, `BaseService[T]`, `EncryptedCharField`. See [docs/data-model.md](../../docs/data-model.md) for class diagrams.
- `core/middleware/` — `RequestIDMiddleware`, `ExceptionLoggingMiddleware`, `RequestLoggingMiddleware`, `RateLimitHeadersMiddleware`. Order matters — see `MIDDLEWARE` in `config/settings/base.py`.
- `core/resilience/` — `@resilient` decorator, circuit breakers (Valkey + PyBreaker fallback), retry, throttles, caches. Full flow in [docs/resilience.md](../../docs/resilience.md).
- `core/exceptions/` — typed hierarchy with `error_code` auto-derived from class name. Status codes registered via `register_exception_mapping()`. See [docs/exceptions.md](../../docs/exceptions.md) for the full hierarchy, decision table, and DRF handler flow.
- `core/responses/` — typed envelopes (`SuccessResponse`, `ErrorResponse`, `PaginatedResponse`). Always use these; never return raw dicts.
- `core/utils/` — `db.py` (SQLAlchemy engine cache + `SqlRowSet`), `http_client.py` (with SSRF guard), `ses.py`, `valkey.py`, `log_sanitization.py`, `pagination.py`, `aws.py` (thread-local boto3 client cache), `logging.py` (`RequestContextFilter`, `domain_context`, `log_duration(metric=...)`).
- `core/metrics.py` — `record_duration` / `record_counter` / `record_gauge` shim. Today every call fans out to `logger.info`; tomorrow tees into `prometheus_client`. The cardinality contract (bounded labels vs log-only identifiers) is enforced at runtime via `_assert_bounded`. See [../../docs/observability.md](../../docs/observability.md) for the contract and the activation procedure.
- `core/middleware/metrics_middleware.py` — `MetricsMiddleware` skeleton, NOT wired today. Activation is a single `MIDDLEWARE` edit after `METRICS_ENABLED=True`.

## Conventions

- **Always use `@resilient("service_name")`** for external calls. See [docs/resilience.md#usage](../../docs/resilience.md) for registration.
- **Never catch in `ExceptionLoggingMiddleware`'s scope** — exceptions that should bubble to the DRF handler must not be caught upstream of it.
- **Never log request bodies.** `RequestLoggingMiddleware` excludes them on purpose.
- **`EncryptedCharField` is fail-closed on decrypt errors.** `from_db_value()` raises `DecryptionError` — callers must handle; the DRF exception handler maps it to 502.
- **`FIELD_ENCRYPTION_KEY` required in non-DEBUG.** Fallback to `SECRET_KEY` only under `DEBUG=True` (emits a warning).
- **Thread-safety contract is binding** for all module-level mutable state. New caches / registries / clients must match a documented pattern in [docs/thread-safety.md](../../docs/thread-safety.md).

## Gotchas

- `BaseService.update()` skips `full_clean()` — serializers must validate, not rely on model-level validation post-service.
- `BaseService.delete(pk, soft=True, user)` is the only correct delete path. Hard delete exists but bypasses cascade audit.
- `_cascade_soft_delete(instance, user=None)` and `post_delete(instance, user=None)` both accept `user` — subclass overrides MUST propagate it so cascade rows get `updated_by` stamped. See [docs/audit-trail.md](../../docs/audit-trail.md).
- Exception status-code map is lazy-frozen with invalidation on write (double-checked locking). Register new exceptions via `register_exception_mapping()`, not by editing the map directly.
- `get_engine()` caches one SQLAlchemy engine per URL per process; it applies 5s connect + 30s statement timeout. Do NOT share that engine across Django ORM transactions.
