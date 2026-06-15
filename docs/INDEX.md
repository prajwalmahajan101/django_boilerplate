# Documentation Index

Every doc in this folder, grouped by topic. New here? Start with the
**Recommended reading order** at the bottom — it's the path that gets
you productive fastest.

## Architecture

- **[architecture.md](architecture.md)** — system overview, layering
  (Views → Services → ORM), encryption, async stack.
- **[class-diagrams.md](class-diagrams.md)** — base hierarchy,
  resilience layering, auth provider chain (Mermaid).
- **[thread-safety.md](thread-safety.md)** — contract for any
  module-level mutable state under gthread Gunicorn + Celery threads.
- **[scalability.md](scalability.md)** — Gunicorn worker × thread
  sizing, Celery topology, fire-and-forget load-shed signal, tuning
  checklist.

## Data & services

- **[data-model.md](data-model.md)** — `BaseModel`, `NamedBaseModel`,
  `BaseService[T]`, the `Meta(BaseModel.Meta)` inheritance contract,
  validation contract, page-size cap, verb hierarchy.
- **[erd.md](erd.md)** — entity-relationship diagram for `User`,
  `Role`, `Permission`, `APIKey`, `ApiLog` (Mermaid).
- **[audit-trail.md](audit-trail.md)** — `created_by` / `updated_by`
  propagation, soft-delete cascade walk, `_cascade_soft_delete_bfs`.

## Authentication & RBAC

- **[authentication.md](authentication.md)** — JWT, Google OAuth,
  API-key auth flow.
- **[sequence-diagrams.md](sequence-diagrams.md)** — wire-level
  diagrams for login, API-key auth, JWT + RBAC.

## Resilience & observability

- **[resilience.md](resilience.md)** — `@resilient` decorator, Valkey
  circuit breaker with PyBreaker fallback, retry, throttle stack.
- **[observability.md](observability.md)** — structured logging,
  metrics shim, cardinality contract, the `MetricsMiddleware`
  activation path.
- **[celery-topology.md](celery-topology.md)** — queue routing,
  priorities, task time-limits.

## Releases

- **[v1.0.0-roadmap.md](v1.0.0-roadmap.md)** — phase plan (M1 CI →
  M2 coverage → M3 gates → M4 ADRs → M5 cut) to reach a stable
  `v1.0.0` matching the fastapi boilerplate's 1.0 quality bar.
- **[m1-ci-hardening-notes.md](m1-ci-hardening-notes.md)** — live
  log from M1 (CI hardening): what shipped, what got deferred, and
  the M3 scope reduction discovered along the way.
- **[m2-coverage-gates-notes.md](m2-coverage-gates-notes.md)** —
  live log from M2 (coverage gates + dormant policy): triage
  decisions, the `deps-check` PyPI-flakiness discovery, and the
  Valkey integration-test scaffolding that closed M1's deferral.
- **[decisions/](decisions/)** — Architecture Decision Records.
  0001 fire-and-forget dispatch · 0002 exception/HTTP registry ·
  0003 CI as the production quality gate.

## Operations

- **[configuration.md](configuration.md)** — every env var, settings
  module overlay, AWS Secrets Manager integration, encryption-key
  rotation runbook.
- **[deployment.md](deployment.md)** — containers, gunicorn flags,
  Celery worker pool sizing.
- **[dependency-management.md](dependency-management.md)** — layered
  pip-tools, hashed lockfiles, `--allow-unsafe` for dev.
- **[development.md](development.md)** — local setup, day-one
  workflow, pre-commit hooks.
- **[testing.md](testing.md)** — pytest layout, fixtures, marker
  conventions, integration-test conftest split.

## Dormant modules

Nine modules ship in-tree for downstream forks but have zero
request-path callers today. The dormant policy has two halves:

1. **Coverage gate** — `.coveragerc`'s `[run] omit` list excludes
   each module, so the gate floor (80% overall as of M2.5) reflects
   only live code.
2. **Import gate** — `scripts/check_dormant_imports.py` walks every
   `.py` under `apps/` + `config/` at pre-commit time and fails on
   any `Import` / `ImportFrom` node that resolves to a dormant
   module. The escape hatch is a same-line
   `# allow-dormant-import: <reason>` comment — reserve it for
   narrow seams (atexit hooks, integration tests, one-shot
   management commands), not for re-activating a module on the
   request path. To activate a dormant module properly, follow the
   per-module recipe below.

The two halves are cross-checked on every run: each `omit` path
must carry a `Dormant:` (or `Dormant (transitively):`) marker in
its module docstring, and vice versa. A mismatch exits the gate
with code 2 before any imports are walked.

### The set + activation procedure

| Module | Activates by | Test to add when activating |
| --- | --- | --- |
| `core/utils/s3.py` | Importing `S3Client` / helpers from a service or task; AWS creds in env | Integration test using `moto` to mock S3 round-trips |
| `core/utils/data.py` | Importing the dataframe helpers from a service that ingests tabular data | Unit test covering each helper against fixture rows |
| `core/utils/filters.py` | Importing `apply_filters` from a list view's `get_queryset` | E2E test asserting a filtered list view returns only matching rows |
| `core/utils/valkey.py` | Importing `ValkeyClient` from a service or middleware that needs raw Valkey access (the resilience kit covers cache + throttle today) | Integration test gated on `VALKEY_AVAILABLE=1`, mirroring `tests/integration/test_valkey_roundtrip.py` |
| `core/utils/ses.py` | Importing `send_email` from a notification service | Integration test using `moto` or a fake SES client |
| `core/utils/function_logger.py` | Decorating a hot-path function with `@log_calls` | Unit test confirming the wrapper emits the expected `extra=` payload |
| `core/utils/aws.py` | Becomes live transitively when `s3.py` or `ses.py` activates; no direct activation expected | Test added with the activating sibling |
| `core/utils/db.py` | Importing `get_engine` / `execute_query` from a service that needs raw SQL (the ORM covers the standard path) | Integration test against the project's test Postgres asserting cache + timeout behaviour |
| `core/middleware/metrics_middleware.py` | Adding the class to `MIDDLEWARE` in `config/settings/base.py` and setting `METRICS_ENABLED=True` | E2E test asserting `X-Request-Duration` (or chosen metric) on a sample response |

When activating: remove the `omit` entry from `.coveragerc`,
remove (or rewrite) the `Dormant:` line from the module docstring,
add the test row above, and the import gate will then require
genuine coverage on the next PR rather than an escape comment.

## Reference

- **[exceptions.md](exceptions.md)** — typed hierarchy, auto-derived
  `error_code`, DRF handler flow, registering domain exceptions.
- **[adding-a-new-app.md](adding-a-new-app.md)** — step-by-step
  contract for onboarding a new domain app (models, RBAC registration,
  exceptions, resilience, Celery routing, soft-delete).
- **[decisions/](decisions/)** — Architecture Decision Records (ADRs).
  Numbered, append-only; start with
  [`0000-template.md`](decisions/0000-template.md) when adding one.

## Recommended reading order

If you're new to the codebase:

1. **[adding-a-new-app.md](adding-a-new-app.md)** — the shortest path
   from zero to a working app; also the best overview of the
   conventions that follow.
2. **[architecture.md](architecture.md)** — once the conventions
   click, see how they fit together.
3. **[data-model.md](data-model.md)** — the reference page for
   everything `BaseModel` / `BaseService` does.
4. Topic-specific docs (resilience, audit trail, authentication) as
   you need them.

The top-level [`CHANGELOG.md`](../CHANGELOG.md) tracks user-visible
changes per release; [`CLAUDE.md`](../CLAUDE.md) (repo root) is the
one-screen convention summary.
