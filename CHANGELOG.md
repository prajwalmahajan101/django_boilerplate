# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `FireAndForgetQueue._dropped` increment is now lock-guarded
  (`apps/core/dispatch/fire_and_forget.py`). Without it the
  read-modify-write under multi-producer load silently
  under-reported the drop counter that ops dashboards key on.
  (ISSUE-031)
- `drain_all(timeout)` honours its argument as a *total*
  budget across registered queues, not per-queue. With N queues
  the prior implementation could block up to `N * timeout`
  seconds on SIGTERM — past the orchestrator grace period.
  Returns `bool` now (was `None`). (ISSUE-030)
- `ResilienceRegistry.register_service` now writes `_services`
  under `self._lock`, matching the documented thread-safety
  contract and avoiding a stale read in `get_breaker`. (ISSUE-032)
- DRF throttle ident now respects proxy hops. Added
  `REST_FRAMEWORK["NUM_PROXIES"]` (env-driven, default `0`) so
  `BaseThrottle.get_ident` strips trusted `X-Forwarded-For` entries
  before bucketing. Without this, every anon client behind nginx
  shared `REMOTE_ADDR=<proxy-ip>` and `BurstThrottle` /
  `AuthThrottle` / `AuthEndpointThrottle` collapsed into a single
  bucket. Set `NUM_PROXIES=1` for nginx, `NUM_PROXIES=2` for
  ALB + nginx. (ISSUE-029)

### Changed
- **Breaking default:** prod cache `KEY_PREFIX` is now env-driven
  (`CACHE_KEY_PREFIX`, default `"app"`). Was hard-coded to
  `"colend"` (donor-project lineage). Adopters upgrading from
  0.2.0 who relied on the implicit `colend` prefix must set
  `CACHE_KEY_PREFIX=colend` in their prod env, or accept that
  cached entries miss on first deploy and the cache repopulates
  under the new namespace. (`config/settings/prod.py`) (ISSUE-027)
- Donor-project lineage (`co-lending-gateway`, `colend`,
  `colender`, `optimoloan`) swept across config (`wsgi.py`,
  `asgi.py`, `prod.py`), tests (`apps/core/tests/test_ses.py`),
  the `http_client.py` docstring example, docs
  (`README.md`, `docs/development.md`, `docs/deployment.md`,
  `docs/configuration.md`, `docs/observability.md`,
  `docs/authentication.md`, `docs/resilience.md`). Generic
  values used instead (`app`, `example.com`,
  `<repository-dir>`). A new adopter's `git grep` for the
  donor name now returns zero hits. (ISSUE-027)
- `scripts/stale_refs.yaml` pattern is now case-insensitive
  (`(?i)`) so capitalised forms (`Co-Lending Gateway` in prose
  vs `co-lending-gateway` in shell commands) can't slip past.
- `scripts/check_stale_refs.py` scope extended to `.py` files under
  `apps/`, `config/`, `scripts/` (was Markdown / CLAUDE.md only).
  Migrations are auto-excluded (intentionally carry historical
  field names). New per-line opt-out marker
  `# stale-refs: allow` lets a single legitimate occurrence
  bypass without dropping scope on the whole file.
- `scripts/stale_refs.yaml` seeded with the donor-project lineage
  family pattern (`co-lending-gateway|colend(er|ing)?|optimoloan`)
  so the next adopter's grep returns zero hits and future
  similar leaks fail the commit. (ISSUE-034)

### Added
- `docs/data-model.md` — reference for `BaseModel`, `NamedBaseModel`,
  `BaseService[T]`, the `Meta(BaseModel.Meta)` inheritance contract,
  the validation contract, and the page-size cap.
- `CHANGELOG.md` — this file. Seeded with the recent batches.
- `docs/adding-a-new-app.md` now documents the
  `register_resource` collision policy.
- `docs/INDEX.md` — documentation landing page with topic grouping
  and recommended reading order for new contributors. Linked from
  `README.md` and the top-level `CLAUDE.md`.
- `apps/core/registries/__init__.py` — canonical namespace re-
  exporting `register_resource` (RBAC) and `register_resilience_service`
  so domain apps have one extension entrypoint.
- `apps/core/resilience/throttles/global_lua.py` — process-wide
  Lua-script cache for `GlobalThrottle`, extracted from `valkey_impl.py`.
- `scripts/check_stale_refs.py` + `scripts/stale_refs.yaml` +
  pre-commit hook `check-stale-refs`. Doc rot from a rename / delete
  now fails the commit; manifest is appended in the same PR as the
  rename.
- `bulk_update` row added to the Write API table in
  `docs/data-model.md`.

### Changed
- `apps/core/api_schemas.py` split into a package
  (`api_schemas/{envelope,responses,system}.py` with re-exports).
  Existing imports unchanged.
- `apps/accounts/CLAUDE.md` now links to `docs/data-model.md` and
  `docs/adding-a-new-app.md`.
- `config/celery.py` and `config/settings/__init__.py`: convert the
  duplicated `sys.path` comment into a proper Decision Record
  explaining why duplication is structural (circular import via
  `config/__init__.py` importing celery) and why it is safe (the
  drift guard catches divergence at boot).
- `CLAUDE.md` Default RBAC resources section now points at
  `core.registries.register_resource()` instead of the deleted
  `RBACBackend.MODEL_RESOURCE_MAP`.

### Fixed
- ISSUE-025 — stale `RBACBackend.MODEL_RESOURCE_MAP` references in
  `CLAUDE.md:74` and `docs/adding-a-new-app.md:159` (checklist item)
  updated to the `register_resource()` pattern. Rephrased the body
  reference at `docs/adding-a-new-app.md:66` so the symbol name no
  longer appears anywhere on the doc surface.
- ISSUE-026 — `bulk_update` was missing from the Write API table
  in `docs/data-model.md`; added with its explicit-`full_clean`
  contract matching `bulk_create`.

### Changed
- `BaseService.list()` page-size cap log promoted from `logger.debug`
  to `logger.warning` so the cap is visible at default
  `LOG_LEVEL=INFO`. Docstring documents the contract.
- `FireAndForgetQueue.drain(timeout)` honours its `timeout` argument
  via a monotonic-deadline poll loop instead of an unbounded
  `_queue.join()`.
- `config/settings/__init__.py` drift guard rewritten with
  `Path(__file__).resolve().parents[2] / "apps"` for readability;
  resolved value unchanged.
- `docs/architecture.md` and `docs/development.md` link to
  `adding-a-new-app.md` and `data-model.md` from the top.

### Fixed
- Stale `encrypted_key` references in `docs/configuration.md`,
  `docs/architecture.md`, and `apps/accounts/CLAUDE.md` updated to
  `secret` after the field rename in 0.2.0. The runbook snippet in
  `docs/configuration.md` no longer raises `FieldDoesNotExist`.
- `apps/accounts/CLAUDE.md` `hmac.compare_digest` corrected to
  `secrets.compare_digest` (matches the actual call site).

## [0.2.0] — 2026-05-29

### Added
- `apps/core/rbac_registry.py` — runtime registry for `Resource ↔ Model`
  mappings. Domain apps register from `AppConfig.ready()` via
  `register_resource()` instead of editing
  `RBACBackend.MODEL_RESOURCE_MAP`.
- `FireAndForgetQueue.is_saturated(threshold=0.9)` — load-shed signal
  callers can check before `submit()`.
- `BaseService.max_page_size` — hard ceiling on `list()` page size.
- `BaseModel.Meta.CheckConstraint(updated_at >= created_at)` — DB-level
  audit invariant; propagates to descendants whose Meta inherits
  `BaseModel.Meta`.
- Partial covering index on `APIKey` matching the auth hot-path
  predicate.
- `apps/core/resilience/throttles/cache_adapter.py` — extracted
  `DjangoCacheAdapter`.
- `docs/adding-a-new-app.md` — checklist for onboarding a new domain
  app.
- `_env_bool` settings helper.

### Changed
- `APIKey.encrypted_key` renamed to `APIKey.secret` (field decrypts on
  read, so the old name described ciphertext while the attribute
  returned plaintext). Includes Django `RenameField` migration.
- Gunicorn CMD adds `--max-requests` / `--max-requests-jitter` /
  `--backlog` for worker recycling and backlog tuning, all env-driven.
- Celery `CELERY_TASK_TIME_LIMIT` / `CELERY_TASK_SOFT_TIME_LIMIT` /
  `CELERY_WORKER_PREFETCH_MULTIPLIER` are env-driven;
  `CELERY_SEND_EVENTS` toggles per-task event emission.
- `APIKeyDeleteView` returns `200` with envelope (was spec-illegal
  `204` with body).
- API-key debounce cache pinned to `caches["rate_limit"]` so default-
  cache swaps don't silently break the 5-minute write-skip.
- Repository `get_queryset()` methods prefetch the RBAC chain by
  default; eliminates N+1 in `RBACBackend.has_perm()`.
- `APIKeyService.revoke()` uses `select_for_update(of=("self",))` to
  shrink the lock scope to the `apikey` row.
- `_cascade_soft_delete` renamed to `_cascade_soft_delete_bfs` to
  surface the algorithm at every call site.
- `FireAndForgetQueue._safe_run` renamed to `_run_task_safely`.
- Audit timestamps (`created_at`, `updated_at`) indexed at the
  `BaseModel` abstract level; `APIKey.revoked_at` indexed.

### Fixed
- 5 Low/P3 issues from the previous review cycle (ISSUE-011, 017, 018,
  019, plus ISSUE-016 documented as Won't-Fix because DRF resolves
  `DEFAULT_AUTHENTICATION_CLASSES` at app-registry population time —
  a module-level import triggers a partial-init `ImportError` at boot).

## [0.1.0] — Initial baseline

- Django 6 + DRF skeleton with vetted core infrastructure (`BaseModel`,
  `BaseService`, typed exceptions, RBAC, `@resilient` decorator,
  structured logging, response envelopes, `EncryptedCharField`).
- Donor-project lineage stripped from boilerplate (commit `ff7ddfb`).
