# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-06-16

First stable cut of the boilerplate. Covers M1–M4 of
[docs/v1.0.0-roadmap.md](docs/v1.0.0-roadmap.md): CI hardening, the
75 → 80% coverage ratchet, the dormant-import AST gate, and the ADR +
docs sweep that follows the resilience-kit migration. No new feature
work; the cut is about lockdown, observability of decisions, and a
clean read for the next adopter.

### Added
- Coverage gate now enforced in CI: overall floor 75% via `.coveragerc
  fail_under` + per-package floors `apps/core/` 75% and `apps/accounts/`
  60% (numbers reflect the honest M2 measurement, not aspirational
  targets — explicit ratchet plan to 85% across 1.x). The existing
  `Pytest — e2e + default suite` step is now `make test-cov`; unit and
  integration tiers stay separate for fast feedback. Per-module wins:
  `apps/core/permissions.py` 15% → 100%, `rbac_registry.py` 62% → 100%,
  `responses/paginated.py` 26% → 100%, `views.py` 38% → 97%,
  `accounts/permissions.py` 0% → 100%; new ~60-test surface across
  `test_permissions.py`, `test_paginated_response.py`, `test_views.py`,
  `test_permissions_helper.py`. Overall: 64.03% → 75.24%. Execution
  log in
  [docs/m2-coverage-gates-notes.md](docs/m2-coverage-gates-notes.md).
  v1.0.0 roadmap § M2.
- Tests for the accounts modules deferred out of M2:
  `accounts/backends.py` 0% → 100%, `accounts/adapters.py` 0% → 100%,
  `accounts/serializers.py` 54% → 98%, `accounts/views.py` 60% → 97%
  (only the OAuth-callback happy path stays uncovered — deferred to a
  dedicated OAuth-coverage PR per the M2.5 plan).
  `core/utils/log_sanitization.py` 73% → 100% (redaction / depth /
  truncation branches). New tests:
  `apps/accounts/tests/test_backends.py`,
  `apps/accounts/tests/test_serializers.py`,
  `apps/accounts/tests/test_adapters.py`,
  `apps/accounts/tests/test_google_login_response.py`,
  `tests/e2e/test_token_refresh_edges.py`,
  `tests/e2e/test_logout.py`, `tests/e2e/test_me_patch.py`,
  `tests/e2e/test_api_key_view_layer.py`,
  `apps/core/tests/test_log_sanitization.py`. E2E suite now clears DRF
  throttle buckets between tests so burst-keyed-by-IP fixtures don't
  leak across cases. v1.0.0 roadmap § M2.5.
- Dormant-module policy (lightweight, prose-only — full AST gate is
  M3). Nine modules carry a `Dormant:` callout in their docstring and
  are omitted from the coverage gate so they don't drag the floor:
  `utils/{s3,data,filters,valkey,ses,function_logger,aws,db}.py` and
  `middleware/metrics_middleware.py`. Each one was verified to have
  zero in-tree callers (or only dormant callers) at M2; the AST gate
  scheduled for M3 will fail the build if anything under `apps/`
  starts importing one of them without a matching integration test.
- Dormant-import AST gate: `scripts/check_dormant_imports.py` +
  `check-dormant-imports` pre-commit hook (v1.0.0 roadmap § M3).
  Fails the build if anything under `apps/` (excluding migrations /
  tests / conftest) imports a `Dormant:`-marked module without a
  matching `# dormant-import: allow <reason>` waiver. Honours the
  waiver across multi-line `from x import (\n a,\n b\n)` statements.
  Unit-tested in `tests/scripts/test_check_dormant_imports.py`.
- First integration test against a real Valkey backend
  (`tests/integration/test_valkey_roundtrip.py`): set/get round-trip
  plus DB-index isolation between the `default` (DB 2) and
  `rate_limit` (DB 3) caches. CI provisions a `valkey/valkey:7`
  service container; the test is opt-in via `VALKEY_AVAILABLE=1` and
  skips cleanly otherwise so local `make test` stays offline. Closes
  M1's deferred-Valkey scope.
- CI (`.github/workflows/test.yml`) now runs the full quality gate
  that local pre-commit + the `make audit/sbom/test-*` targets
  already enforce: `pre-commit run --all-files` (ruff + pydocstyle +
  darglint + five AST guards — `check_dead_utils`, `check_layering`,
  `check_thread_safety`, `check_openapi_metadata`,
  `check_stale_refs`), `make audit` (pip-audit against
  `requirements/prod.txt`), `make sbom-diff` (CycloneDX SBOM drift),
  and `pytest` split into unit / integration / e2e tiers so a flaky
  e2e doesn't blur a unit regression. Rationale captured in
  [ADR-0003](docs/decisions/0003-ci-as-quality-gate.md); execution
  log in [docs/m1-ci-hardening-notes.md](docs/m1-ci-hardening-notes.md).
  v1.0.0 roadmap § M1.
- ADRs for the v1.0.0 architecture surface:
  [ADR-0004 outsource resilience to `resilience-kit`](docs/decisions/0004-outsource-resilience-to-resilience-kit.md)
  (captures the M7/M8 kit migration: in-tree bridges only, kit owns
  circuit-breaker / retry / throttle / SSRF / Fernet), and
  [ADR-0005 dormant-module policy](docs/decisions/0005-dormant-module-policy.md)
  (the contract behind the M3 AST gate). v1.0.0 roadmap § M4.
- `docs/data-model.md` — reference for `BaseModel`, `NamedBaseModel`,
  `BaseService[T]`, the `Meta(BaseModel.Meta)` inheritance contract,
  the validation contract, and the page-size cap.
- `CHANGELOG.md` — this file. Seeded with the recent batches.
- `docs/adding-a-new-app.md` now documents the
  `register_resource` collision policy.
- `docs/INDEX.md` — documentation landing page with topic grouping
  and recommended reading order for new contributors. Linked from
  `README.md` and the top-level `CLAUDE.md`. Surfaces all five ADRs
  by name and documents the dormant-modules activation procedure.
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
- Coverage floors ratcheted to **80%** (was 75% overall, 75% `apps/core/`,
  60% `apps/accounts/`). `.coveragerc fail_under = 80`; CI floors
  `apps/core/` 75 → 80 and `apps/accounts/` 60 → 80 in
  `.github/workflows/test.yml`. Honest-measurement principle from M2
  applies: post-ratchet measurement is overall **84.09%**, `apps/core/`
  **80.80%**, `apps/accounts/` **95.60%**. v1.0.0 roadmap § M2.5.
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
- `scripts/stale_refs.yaml` extended to gate kit-migrated paths
  (in-tree resilience / encryption modules deleted by the M7/M8
  cut) so the doc surface can't quietly drift back to the old
  paths. Remaining in-tree references swept in the same pass.
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
- `BaseService.list()` page-size cap log promoted from `logger.debug`
  to `logger.warning` so the cap is visible at default
  `LOG_LEVEL=INFO`. Docstring documents the contract.
- `FireAndForgetQueue.drain(timeout)` honours its `timeout` argument
  via a monotonic-deadline poll loop instead of an unbounded
  `_queue.join()`.
- `docs/architecture.md` and `docs/development.md` link to
  `adding-a-new-app.md` and `data-model.md` from the top.

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
- ISSUE-025 — stale `RBACBackend.MODEL_RESOURCE_MAP` references in
  `CLAUDE.md:74` and `docs/adding-a-new-app.md:159` (checklist item)
  updated to the `register_resource()` pattern. Rephrased the body
  reference at `docs/adding-a-new-app.md:66` so the symbol name no
  longer appears anywhere on the doc surface.
- ISSUE-026 — `bulk_update` was missing from the Write API table
  in `docs/data-model.md`; added with its explicit-`full_clean`
  contract matching `bulk_create`.
- Stale `encrypted_key` references in `docs/configuration.md`,
  `docs/architecture.md`, and `apps/accounts/CLAUDE.md` updated to
  `secret` after the field rename in 0.2.0. The runbook snippet in
  `docs/configuration.md` no longer raises `FieldDoesNotExist`.
- `apps/accounts/CLAUDE.md` `hmac.compare_digest` corrected to
  `secrets.compare_digest` (matches the actual call site).

### Refactored
- `apps/core/api_schemas.py` split into a package
  (`api_schemas/{envelope,responses,system}.py` with re-exports).
  Existing imports unchanged.
- `config/settings/__init__.py` drift guard rewritten with
  `Path(__file__).resolve().parents[2] / "apps"` for readability;
  resolved value unchanged.

### Security
- Bumped four transitively-vulnerable packages flagged by the M1
  pip-audit gate on its first real run: `django` 6.0.5 → 6.0.6
  (5 PYSEC advisories), `tornado` 6.5.5 → 6.5.7 (CVE-2026-49854),
  `idna` 3.14 → 3.18 (CVE-2026-45409), `pyjwt` 2.12.1 → 2.13.0
  (4 PYSEC advisories). All bumps stayed inside existing
  `requirements/*.in` ranges; no breaking changes; 180 tests still
  pass. Caught by the same `make audit` step landed alongside; see
  M1 phase journal for the discovery log.
- `cryptography` 48.0.0 → 49.0.0 (GHSA-537c-gmf6-5ccf). Pinned
  via `requirements/base.in`; transitive consumers re-locked.
- SSRF guard is now DNS-pinned across the validate → request
  boundary, closing the DNS-rebinding TOCTOU. Previously
  `_assert_public_url` resolved the hostname via `getaddrinfo`
  and validated each IP, then `requests` did its own DNS lookup
  at request time — an attacker controlling the zone could
  return a public IP on the first lookup and a private IP on
  the second. The new `_resolve_and_validate` returns the IPs,
  and `make_http_request` pins them on a thread-local before
  `requests` runs so the resolution is shared. `OUTBOUND_URL_ALLOWLIST`
  remains load-bearing — see `docs/resilience.md` for why
  (redirects + the `trusted=True` opt-out). (ISSUE-028)

### Documentation
- `EncryptedCharField` class docstring now warns that equality
  lookups against the column do not work — Fernet's random IV
  means re-encrypting the filter value never matches. Suggests
  the sidecar lookup column pattern (`APIKey.prefix`) for any
  new model that needs to look up by an encrypted value.
  Mirrored in `docs/data-model.md` as a published reference
  section. (ISSUE-033)
- `docs/configuration.md` clarifies that `EncryptedCharField` is
  now owned by `resilience-kit` (re-exported from
  `apps/core/models/fields.py` for path stability) and documents
  the `RESILIENCE_*` env-var overlay that overrides kit defaults.
- `docs/resilience.md` updated so every code reference points at
  the kit import path (e.g. `resilience_kit.circuit_breaker`)
  instead of the deleted in-tree modules.

### Versioning note
This project ships as a Django application boilerplate, not a Python
package, so it intentionally carries **no `[project].version` field
in `pyproject.toml`**. The authoritative version lives in the git tag
(`v1.0.0`) and the matching `## [1.0.0]` heading above. Adopters
should pin by tag or commit, not by version string in metadata.

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
