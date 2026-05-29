# Documentation Index

Every doc in this folder, grouped by topic. New here? Start with the
**Recommended reading order** at the bottom — it's the path that gets
you productive fastest.

## Architecture

- **[architecture.md](architecture.md)** — system overview, layering
  (Views → Services → ORM), encryption, async stack.
- **[thread-safety.md](thread-safety.md)** — contract for any
  module-level mutable state under gthread Gunicorn + Celery threads.
- **[scalability.md](scalability.md)** — Gunicorn worker × thread
  sizing, Celery topology, fire-and-forget load-shed signal, tuning
  checklist.

## Data & services

- **[data-model.md](data-model.md)** — `BaseModel`, `NamedBaseModel`,
  `BaseService[T]`, the `Meta(BaseModel.Meta)` inheritance contract,
  validation contract, page-size cap, verb hierarchy.
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

## Reference

- **[exceptions.md](exceptions.md)** — typed hierarchy, auto-derived
  `error_code`, DRF handler flow, registering domain exceptions.
- **[adding-a-new-app.md](adding-a-new-app.md)** — step-by-step
  contract for onboarding a new domain app (models, RBAC registration,
  exceptions, resilience, Celery routing, soft-delete).

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
