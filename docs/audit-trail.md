# Audit trail

Every mutating operation stamps four fields on the affected row: `created_by`,
`updated_by`, `created_at`, `updated_at`. The mechanism is uniform via
`BaseService` hooks — but the **cascade path** (how those stamps propagate
through soft-deletes of a parent row and its children) is subtle enough to
deserve its own reference.

> **Base class:** `apps/core/base/service.py::BaseService` ·
> **Model fields:** `apps/core/base/model.py::BaseModel` ·
> **Conventions:** [../apps/core/CLAUDE.md](../apps/core/CLAUDE.md)

## Audit fields

Defined on `BaseModel` (abstract; all domain models inherit):

| Field | Type | Populated by |
|---|---|---|
| `created_by` | `FK(User, null=True, SET_NULL)` | `BaseService.create` (from `user` arg) + any admin `save_model` override. |
| `updated_by` | `FK(User, null=True, SET_NULL)` | `BaseService.update` / `BaseService.delete` + every cascade soft-delete call that carries a user. |
| `created_at` | `DateTimeField(auto_now_add=True)` | Django — set automatically on INSERT. |
| `updated_at` | `DateTimeField(auto_now=True)` | Django — set automatically on every `.save()`. **NOT** set by `QuerySet.update()` or `bulk_update()` — must be included in `update_fields` / kwargs explicitly. |

## BaseService hook sequence (create / update)

```mermaid
sequenceDiagram
    participant V as View
    participant S as Service (BaseService[T])
    participant M as Model instance
    participant DB as PostgreSQL

    V->>S: create(data, user)  or  update(pk, data, user)
    S->>S: pre_create / pre_update(data, user)<br/>→ may augment data
    S->>M: Model(**data)  /  setattr(instance, ...)
    S->>DB: @transaction.atomic<br/>INSERT / UPDATE (with select_for_update on update)
    DB-->>S: row committed (created_at/updated_at auto-stamped)
    S->>S: post_create / post_update(instance, user)<br/>→ domain hooks
    S-->>V: return instance
```

## Audit field decision table

For every mutating operation, this is which audit fields get stamped and by
which hook.

| Operation | `created_by` | `updated_by` | `created_at` | `updated_at` | Stamped by |
|---|---|---|---|---|---|
| `service.create(data, user)` | **user** | — | auto (INSERT) | auto (`.save()`) | `BaseService.create` sets `created_by` when the model has the field. |
| `service.update(pk, data, user)` | unchanged | **user** | unchanged | auto (`.save()`) | `BaseService.update` sets `updated_by` after `pre_update`. |
| `service.delete(pk, user)` — soft delete, main row | unchanged | **user** | unchanged | explicit (`.save(update_fields=[..., "updated_at"])`) | `BaseService.delete` includes `updated_at` and `updated_by_id` in `update_fields`. |
| `service.delete(pk, user)` — cascade to CASCADE FK children | unchanged | **user** (propagated) | unchanged | explicit (`QuerySet.update(updated_at=..., updated_by=...)`) | `_cascade_soft_delete_bfs(instance, user=user)` passes both fields to `.update()` for every related queryset. |
| `service.delete(pk, user)` — subclass `post_delete` cascading manually | unchanged | **user** (propagated) | unchanged | explicit | Subclass-overridden `post_delete(instance, user=None)` runs `bulk_update`. Override **MUST** accept `user` and forward it. |
| Bulk operations via `service.bulk_update(instances, fields)` | unchanged | only if caller set it on each instance | unchanged | only if `"updated_at"` is in `fields` | `bulk_update` is a thin wrapper — audit stamping is the caller's responsibility. |
| System-triggered updates (no user) | unchanged | **NOT stamped** | unchanged | auto / explicit | When the actor is the system (scheduled job, signal handler), pass `user=None` so audit doesn't misattribute the change. |

## Cascade soft-delete flowchart

The end-to-end propagation when a row is soft-deleted and that soft-delete
must cascade to CASCADE-FK children.

```mermaid
flowchart TD
    A[POST /api/.../DELETE entry point] --> B[View: service.delete pk, soft=True, user]
    B --> C[BaseService.delete]
    C --> D["@transaction.atomic begins"]
    D --> E[pre_delete instance]
    E --> F[instance.is_active = False<br/>set updated_by]
    F --> G[instance.save update_fields=is_active,<br/>updated_at, updated_by_id]
    G --> H["_cascade_soft_delete_bfs(instance, user)"]
    H --> I{Iterate related<br/>CASCADE FK descriptors}
    I --> J["For each related queryset:<br/>related.filter(is_active=True)<br/>.update(is_active=False,<br/>updated_at=now,<br/>updated_by=user)"]
    J --> K[Recurse into each child<br/>_cascade_soft_delete_bfs child, user]
    K --> I
    I --> L["post_delete(instance, user)"]
    L --> M{Subclass override?}
    M -- yes --> N[Subclass-specific cascade<br/>must propagate user]
    M -- no --> O[Commit]
    N --> O
    O --> P[HTTP 200]
```

The key invariants enforced by this design:

1. **`updated_by` reaches every row touched by the cascade.** No row flips
   `is_active=False` with a stale `updated_by` attribution.
2. **`updated_at` is explicit in every cascade `.update()` / `bulk_update`.**
   Django does not auto-stamp `auto_now` during `QuerySet.update()` —
   forgetting `updated_at` silently leaves the old timestamp.
3. **Subclasses that override `post_delete` MUST accept `user=None` and
   forward it.** The base signature is `post_delete(instance, user=None)`;
   every override must respect the `user` argument or cascade rows end up
   with NULL `updated_by`.
4. **Cascade depth is bounded** by `BaseService.MAX_CASCADE_DEPTH`
   (default 10). The walk is breadth-first; at the cap the cascade
   short-circuits and logs WARNING with `model`, `pk`, and `depth`.
   This protects against circular soft-FK chains a future contributor
   might introduce. Subclasses can override the class attribute if a
   legitimate cascade exceeds 10 levels — but consider whether the
   cycle is the actual bug first.

## Failure modes to watch for

- **Forgetting `updated_at` in `bulk_update` `update_fields`.** Django's
  `auto_now` only fires on `.save()`. Every cascade `bulk_update` must list
  both `updated_at` and `updated_by` explicitly.
- **`.update(is_active=False)` without audit fields.** `QuerySet.update`
  bypasses `.save()` entirely; neither auto-field fires. Always build the
  kwargs: `.update(is_active=False, updated_at=timezone.now(), updated_by=user)`.
- **Cascade hook that swallows `user`.** If `post_delete(instance)` doesn't
  accept `user`, the cascade rows end up with NULL `updated_by`.
- **Direct ORM edits bypassing the service layer.** Programmatic shell edits
  via `Model.objects.filter(...).update(...)` skip every hook. Shell sessions
  should go through the service layer when audit matters; otherwise stamp
  `updated_at` / `updated_by` by hand.
- **`created_by` on creation when the actor is the system.** Passing
  `user=None` to `service.create()` leaves `created_by` NULL — that's the
  correct state for system-created rows; downstream code must tolerate NULL
  on either audit field.

## API audit log pipeline (`apps/core/api_log/`)

The row-level audit fields above cover *what changed in our data*. The
api_log pipeline covers *what crossed the process boundary* — every
inbound HTTP request and every outbound HTTP call captured into a
single queryable table, asynchronously, with no request-path latency.

### Inbound / Outbound capture

- **Inbound** — `@log_inbound("service_name")`
  (`core/api_log/inbound.py`) stamps the request and its response into
  the audit pipeline after the view returns. Captures method, path,
  status, duration, the authenticated principal, the request and
  response bodies (after sanitization), and the `request_id` for
  correlation.
- **Outbound** — `core.utils.http_client.make_http_request` emits a
  matching audit entry for every outbound call via
  `core/api_log/outbound.py`: URL host, method, status, duration, the
  outbound payload, and the upstream response body. Failures (timeout,
  SSRF refusal, non-2xx) go through
  `core.exceptions.utils.normalize_outbound_exception` so the row has
  a consistent `status_code` / `response_body` shape regardless of
  which typed exception fired.
- **Sanitization** — `core/api_log/sanitizers.py` strips known
  credential headers (`Authorization`, `X-API-Key`, cookies), redacts
  PII fields, and caps payload size. Anything that would violate the
  bounded-cardinality contract from
  [observability.md](observability.md#cardinality-contract) is
  rejected before write.
- **Persisted-body redaction guarantee** — every `api_logs` row goes
  through `core.api_log.sanitizers.serialize_body`, which delegates to
  `core.utils.log_sanitization.sanitize_for_log` *before* JSON
  encoding. Keys matching the configured `SENSITIVE_PATTERN`
  (default: `password|secret|token|key|auth|credential|api_key|bearer
  |jwt`) and the `EXCLUDED_FIELDS` set (default: `password`,
  `secret_ref`, `api_key`, `private_key`, `access_token`) are masked
  or dropped at write time. The guarantee covers every call site:
  inbound request body, inbound response data, outbound request body
  (via `HttpResponse.request`), outbound response body, and the
  scalar fields of multipart form uploads. Strings and bytes that
  parse as JSON are recursively redacted; non-JSON scalars fall
  through to control-char escaping + length cap. Configuration lives
  in `LOG_SANITIZATION` in `config/settings/base.py`.

### Dispatch pipeline

Writes go through the fire-and-forget queue documented in
[ADR-0001](decisions/0001-fire-and-forget-dispatch.md):

1. The decorator hands the row to `core.dispatch.fire_and_forget`.
2. The dispatcher pushes it onto a bounded in-process queue.
3. A background worker thread drains the queue into the configured
   backend (DB row writer today).
4. On overflow, the row is **dropped** with a `WARNING` log
   (`event=fire_and_forget_overflow`) so operators see saturation
   loudly. Dropping is preferable to slowing the request path.
5. On process shutdown, `core.lifecycle` triggers a bounded
   drain — pending rows get up to the configured deadline to flush
   before the worker exits.

### Backends

Pluggable via the `ApiLogBackend` `typing.Protocol` in
`core/api_log/backends/base.py`. The default `OrmApiLogBackend`
(`backends/orm.py`) writes to the `ApiLog` model; `NoopApiLogBackend`
(`backends/noop.py`) is the test seam. Adding a new sink (CloudWatch,
Kinesis, BigQuery) is one new class implementing the protocol plus a
registry binding — no decorator changes required.

### Querying

`ApiLog.objects` honours the standard Django ORM. For incident triage
the most useful filter is `request_id` — every row that participated
in a single client request shares it (inbound + every outbound called
during the request). Pair with the
[observability.md triage table](observability.md#quick-where-do-i-look)
to turn a `request_id` from a 5xx response into a complete timeline in
under a minute.

## Related docs

- [../apps/core/CLAUDE.md](../apps/core/CLAUDE.md) — BaseModel / BaseService
  conventions including the hook contract.
- [architecture.md](architecture.md) — where the service layer sits.
- [exceptions.md](exceptions.md) — error-handling boundaries around service
  methods.
- [decisions/0001-fire-and-forget-dispatch.md](decisions/0001-fire-and-forget-dispatch.md) — why the api_log queue drops on overflow.
- [observability.md](observability.md) — metrics contract + the triage
  table the `request_id` cross-link references.
