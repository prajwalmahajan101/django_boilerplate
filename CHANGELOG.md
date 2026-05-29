# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/data-model.md` — reference for `BaseModel`, `NamedBaseModel`,
  `BaseService[T]`, the `Meta(BaseModel.Meta)` inheritance contract,
  the validation contract, and the page-size cap.
- `CHANGELOG.md` — this file. Seeded with the recent batches.
- `docs/adding-a-new-app.md` now documents the
  `register_resource` collision policy.

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
