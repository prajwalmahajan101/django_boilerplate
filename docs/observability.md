# Observability

> Companion to [development.md](development.md#observability) — that page covers structured logging; this page covers metrics, the cardinality contract, and the Prometheus + Grafana activation procedure.

## State today (Phase 1b of the score-lift plan)

The codebase is **prepared for** Prometheus + Grafana, but the exporter is **not running**. Concretely:

- `apps/core/metrics.py` is the canonical entry point — `record_duration`, `record_counter`, `record_gauge`. Today every call fans out to `logger.info` with a structured `extra=` payload. Log aggregation consumes the same payloads.
- `prometheus-client` is already a **transitive dependency** in the lock files (pulled in by another package — `requirements/prod.in` does not declare it explicitly). This is convenient: activation does not need an explicit `pip install`. Verify importability at deploy time.
- The `/api/metrics` URL slot is wired and returns **HTTP 503** with body `metrics exporter not configured` while `METRICS_ENABLED=False` (the default).
- `apps/core/middleware/metrics_middleware.py` exists but is **commented out** in `MIDDLEWARE`. Wiring it is part of activation.
- Commit a Grafana dashboard JSON at `ops/grafana/<project>.json` referencing the metric names below. Every panel shows "No data" until activation; they light up after activation without further changes.

## Cardinality contract

The fatal failure mode of Prometheus instrumentation is unbounded label cardinality — labelling a histogram by `request_id` creates one time series per request and crashes the scrape. The contract below is enforced **at runtime** by `core.metrics._assert_bounded`: a wrong call site raises `CardinalityViolation` the first time it's exercised, not after the `prometheus-client` install lands.

### Bounded labels — safe for metrics + logs

| Label | Domain | Notes |
|---|---|---|
| `event` | enum-like, ~20 values | e.g. `s3_upload`, `ses_send_email`, `external_query` |
| `subsystem` | `cache`, `breaker`, `throttle`, `outbox`, `dispatch` | resilience subsystems |
| `status` | `ok`, `error` | duration / counter success indicator |
| `outcome` | `success`, `timeout`, `breaker_open`, `permission_denied` | classification of error paths |

### Unbounded labels — LOGS ONLY, never metrics

`request_id`, `app_number`, `query_id`, `partner_id` (the integer FK — use `partner_slug` for metrics), `user_id`, `remark_id`, `outbox_id`.

These belong on the structured log record via the `domain_context(...)` ContextVar block in `core.utils.logging`. They reach log aggregation through the `extra=` payload but never leave the log lane.

### Forbidden in both

Anything containing PII (email, phone, PAN, Aadhaar), raw URLs, or raw error message strings. Forbidden keys are listed by name in `core.metrics._FORBIDDEN_LABEL_KEYS` so the rejection message at the call site is clear.

## Metric naming vocabulary

`app_<verb>_<object>_<unit>`. Examples:

- `app_s3_upload_duration_seconds` (histogram)
- `app_ses_send_email_duration_seconds` (histogram)
- `app_valkey_subsystem_degraded` (gauge, labeled by `subsystem`)
- `app_task_outbox_depth` (gauge — undelivered outbox rows)
- `app_task_outbox_attempts_total` (counter)
- `app_circuit_breaker_state` (gauge, labeled by `subsystem`)

The prefix is project-wide; pick something specific (`acme_`, `payments_`, etc.) and apply it uniformly when you fork this boilerplate. If you ship a Grafana dashboard, pair it with a regression test that parses the dashboard JSON and pins each metric name so renames touch both sites in lockstep.

## How call sites emit metrics today

Two paths, both correct:

1. **Through `log_duration(metric=True)`** — the canonical hot-path pattern. `log_duration` already times the block and logs structured `duration_ms`; passing `metric=True` additionally tees the duration into `record_duration`. The shim filters extras down to the bounded allow-list before forwarding, so a hot path can keep stamping `app_number` / `partner_id` on the log without those keys reaching the metric.

   ```python
   with log_duration(
       logger,
       "partner_push",
       metric=True,
       partner_slug=partner.code,    # bounded -> metric label
       partner_id=partner.pk,        # unbounded -> log only
       app_number=app_number,        # unbounded -> log only
   ):
       ...
   ```

2. **Direct `core.metrics.record_*` calls** — for slow-moving state that isn't a duration (outbox depth gauge, breaker state gauge). Every call goes through `_assert_bounded`, so a forbidden label key crashes the call at the line that introduced it.

## Activation procedure (production)

When the time comes to actually run Prometheus:

1. Confirm `prometheus-client` is importable (`python -c "import prometheus_client"`). It is currently transitive — if a future dep prune removes it, add it to `requirements/prod.in` explicitly and rebuild `prod.txt` via the pip-compile workflow in `docs/dependency-management.md`.
2. Set `METRICS_ENABLED=true` and `METRICS_ALLOWED_IPS=<scraper CIDR>` in the environment.
3. Add `core.middleware.metrics_middleware.MetricsMiddleware` to the `MIDDLEWARE` list in `config/settings/base.py` (the class exists in this phase but is not referenced anywhere).
4. Deploy.
5. Confirm `/api/metrics` returns HTTP 200 with Prometheus text format from the scraper's source IP.
6. Point the Grafana instance at the project's dashboard JSON under `ops/grafana/` (import or sync via provisioning).

**No code changes required.** Every call site already shapes data correctly for the cardinality contract. That's the whole point of the prep phase.

## Request ID propagation

Every request gets a correlation ID — either honoured from the inbound
`X-Request-ID` header (validated by `_REQUEST_ID_PATTERN` in
`core/middleware/request_id.py:12`) or minted as a UUIDv4 — and that
single ID threads through:

- **`request.request_id`** — set by `RequestIDMiddleware` before the view runs.
- **`core.context.request_id_ctx`** — `ContextVar` bound for the duration of
  the request. The middleware captures the reset token and restores it on
  exit so nested Celery dispatch (or any inner `set_request_context`) does
  not bleed IDs across the request boundary.
- **Every log record** — `core.utils.logging.RequestContextFilter` stamps
  `record.request_id` from the ContextVar.
- **Every `BaseCustomError`** — captured at `__init__` time
  (`core.base.exception.BaseCustomError.__init__`) so the response envelope
  echoes the same ID back to the client.
- **The `X-Request-ID` response header** — set unconditionally on the
  outbound response.

Operators tracing an incident pull the ID once from the client's response
and follow it through every log line, audit row, and error envelope without
joining tables.

## Recovery monitor

`core/resilience/recovery.py` runs a background monitor that watches every
resilience provider whose Valkey alias degraded at boot (or after a runtime
cache failure). It polls each degraded backend on a fixed cadence and
resets the cached client once Valkey comes back, without restarting the
process.

Operational signals:

- `registered backend for recovery monitor` (INFO) — emitted at boot for
  every resilience alias that opted into recovery polling.
- `ValkeyRecoveryMonitor started` (INFO) — the background polling thread
  launched.
- Look for log records carrying `event=backend_register` and
  `alias=<cache name>` to confirm a degraded provider is being watched.

The monitor is the reason a transient Valkey hiccup does not require a
deploy — leave it running.

## Health probes

Two endpoints, served by `core/views.py` and wired in `core/urls.py`:

- **`GET /health/`** — liveness. Succeeds whenever the process is up; never
  checks a downstream dependency. Use this for kubelet `livenessProbe`.
- **`GET /readiness/`** — readiness. Consults each resilience provider's
  `is_healthy()` (cache, throttle, breaker backends) plus the audit
  pipeline. A `503` here means **degraded but serving** — the load
  balancer should drain the pod, but in-flight requests still complete.

The response envelope is the standard `SuccessResponse` / `ErrorResponse`
shape: `{success, message, data, errors, request_id}`. Anonymous probes
(load balancers, kubelet) get the masked body so the dependency topology
is not leaked. Adding a new dependency to readiness is one entry in
`core/lifecycle/healthcheck.py`; the standard `LifecycleCheck` interface
returns `(name, ok, detail)`.

## Quick "where do I look?"

When a symptom lands, this table maps it to the first place to check.
Pair with a fresh `request_id` from the client's response and most
incidents resolve in one or two hops.

| Symptom | First place to look |
|---|---|
| 401 / 403 spike | `RequestLoggingMiddleware` records + the api_log row (`auth_provider` field); confirm the auth provider that ran |
| Upstream 5xx from us | Circuit breaker state — grep logs for `breaker_open` / `event=breaker_state`; check the `subsystem` label |
| Rate-limit denials | `Retry-After` + `X-RateLimit-*` headers in the client's response; throttle scope counters in cache |
| Slow request | `RequestLoggingMiddleware` `duration_ms` + the matching `log_duration` block in the hot path |
| Missing log entry | Sanitizer caps — `core.utils.log_sanitization` truncates oversized payloads; check the `truncated=true` flag |
| 502 with empty body | Outbound HTTP failure — look for `OutboundURLNotAllowedError` / `ExternalTimeoutError` / `APIError` and the http_client INFO line carrying `host` + `status_code` |
| Decrypt failure on a field | `DecryptionError` traceback in error logs; usually the `FIELD_ENCRYPTION_KEY` rotated without a re-encrypt pass |
| Valkey alias stuck degraded | `ValkeyRecoveryMonitor` records for that alias — if no `recovered` line shows up, the backend is genuinely down |

## Why this earned an Architecture score-lift

The `core.metrics` shim is a genuine new boundary. Services emit *intent* (record this event); the shim decides the *destination* (log today, log + metric tomorrow). Same shape as the existing `core.exceptions` / `core.responses` boundaries — call sites don't change when the implementation does. Future-proofing that's actually executable (a Grafana JSON file you can import) is more durable than future-proofing that's just documentation.
