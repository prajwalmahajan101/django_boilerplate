# resilience-kit 0.1.0rc1 — django_boilerplate M7 integration log

> Living notes captured **while** migrating django_boilerplate to the
> published kit. Feeds the audit report at
> `docs/m7-kit-integration-report.md` (task #21).
> One entry per friction point or praise-worthy moment. Don't reconstruct
> — write it down when you hit it.

## Legend

- **P0** — blocks the documented migration path; needs a kit fix or doc fix.
- **P1** — usable workaround exists; rough edges that hurt ergonomics.
- **P2** — nice-to-have, polish, or surface-area gap with low blast radius.
- **PRAISE** — design choice that paid off during integration.

---

## Step 1 — Pin + lock

- **PRAISE** — extras (`[django,redis,http,crypto,audit-postgres]`) compose
  cleanly. `pip-compile --generate-hashes` finishes without conflict; kit
  pulls `tenacity`, `pybreaker`, `httpx`, `cryptography`, `pydantic-settings`
  transitively so the boilerplate can drop direct pins (step 8 candidate).
- **P2** — kit metadata advertises `0.1.0rc1` on PyPI but the MIGRATION
  doc still tells users to `git+ssh://…@milestone/m7-rc1`. Doc fix only.

## Step 2 — Settings

- **P0** — MIGRATION §3 promises a `DjangoSettingsSource` that reads
  `settings.RESILIENCE`. `resilience_kit/adapters/django/apps.py:64-74`
  only reads `RESILIENCE["services"]`; defaults / crypto / ssrf / audit /
  rate_limit_headers keys are silently ignored. Kit settings only come
  from `RESILIENCE_*` env vars via pydantic-settings.
  - **Workaround**: keep the `RESILIENCE` dict for human readability and
    populate the matching `RESILIENCE_*` env vars at `settings/base.py`
    import time so the kit picks them up.
  - **Ask kit**: ship a real `DjangoSettingsSource` so the dict shape in
    the MIGRATION doc actually works — projects expect Django-native
    config, not env-only.
- **P1** — env-var contract is incompatible with the boilerplate's
  existing names: `RATE_LIMIT_ANON`, `CIRCUIT_BREAKER_FAIL_OPEN`,
  `FIELD_ENCRYPTION_KEY` → `RESILIENCE_DEFAULTS__THROTTLE__ANON_RATE`,
  `RESILIENCE_FAIL_OPEN`, `RESILIENCE_CRYPTO__FIELD_ENCRYPTION_KEY`. Any
  deploy that doesn't update env files silently loses tuning.
  - **Ask kit**: support legacy aliases or document a translation snippet
    projects can paste into `settings/base.py`.
- **P1** — DRF `EXCEPTION_HANDLER` swap (MIGRATION §5 ¶3) breaks the
  boilerplate envelope because kit's `handle()` only catches
  `ResilienceKitError` and defers everything else to DRF's flat
  `{detail: …}` response. Doc should call out the composition pattern.
- **PRAISE** — `INSTALLED_APPS += ["resilience_kit.adapters.django"]` is
  a clean one-liner; the AppConfig owns its own lifecycle (monitor +
  audit drain). No `urls.py` mount, no `MIDDLEWARE` re-ordering surprises.

## Step 3 — MIDDLEWARE swap

- **PRAISE** — six middleware classes drop cleanly, same `process_request`
  / `process_response` semantics. RequestId ContextVar plumbing matches
  the boilerplate's existing helper so downstream `core.context.get_request_id`
  still works without an adapter.
- **P2** — Class naming diverged from upstream Django convention:
  `SelectiveCorsMiddleware` (lowercase `s`) vs boilerplate's
  `SelectiveCORSMiddleware`. Minor; just a string in `MIDDLEWARE`.

## Step 4 — CoreConfig.ready

- **PRAISE** — moving recovery-monitor lifecycle into the kit's AppConfig
  removes ~20 lines of `_start_recovery_monitor` + atexit + autoreload
  guard. Less stuff for the boilerplate to maintain.
- **P1** — `registry.register_service(..., excluded_exceptions=("…",))`
  takes import paths as **strings**. Works, but the boilerplate's S3
  exclusion now uses `core.exceptions.infrastructure.S3NotFoundError`
  while the rest of the resilience config lives kit-side. Cross-package
  string refs are fragile under renames.
  - **Ask kit**: accept exception **classes** in addition to strings,
    or document the resolution order.

## Step 5 — DRF throttles

- **P1** — kit ships `IPThrottle`, `UserTierThrottle`, `BurstThrottle`,
  `EndpointThrottle`, `AuthThrottle` but **no `GlobalThrottle`**. The
  boilerplate's process-wide 10 000/min cap (Lua-backed) is dropped.
  - **Ask kit**: port the boilerplate's `GlobalThrottle` (Lua script
    lives at `apps/core/resilience/throttles/global_lua.py`) — it's a
    well-trodden production pattern; one more class on the kit's
    surface keeps in-process belts-and-braces with nginx.
- **PRAISE** — class names align (`UserTierThrottle`, `BurstThrottle`,
  `EndpointThrottle`) so `DEFAULT_THROTTLE_CLASSES` is a string-only
  edit. No view code changes needed at the settings level.

## Step 6 — EncryptedCharField (in progress)

- **P0** — kit's `crypto.environment` defaults to `prod` and
  `FernetCipher` refuses the missing-key fallback (raises
  `EncryptionConfigError`). The boilerplate's local/test path relied on
  `FIELD_ENCRYPTION_KEY or SECRET_KEY` with a warning. Tests will break
  the first time a fixture touches `APIKey.secret`.
  - **Workaround**: set `RESILIENCE_CRYPTO__ENVIRONMENT=dev` in
    `settings/{local,test}.py`, generate a deterministic Fernet key for
    test fixtures.
  - **Ask kit**: ship a `crypto.allow_secret_key_fallback` flag or a
    documented test fixture that auto-supplies a key in `environment=dev`.
- **P2** — `EncryptedCharField.deconstruct()` returns the kit's path;
  Django generates a no-op migration purely for the import path
  rewrite. Annoying but unavoidable for downstream consumers.

## Step 7 — Codemod + exception bridge + handler composition

- **P0** — kit ships no `resilience_kit.utils` sub-package, but MIGRATION
  §2 row "`core/utils/{log_sanitization,function_logger,network,timing,
  data}.py` delete → `from resilience_kit.utils.{…} import …`" claims it
  does. Verified via `ModuleNotFoundError: No module named
  'resilience_kit.utils'`. Boilerplate has to **keep**
  `core/utils/{log_sanitization,network,timing,function_logger,data}.py`
  — Step 8 deletion list trimmed.
  - **Ask kit**: ship `resilience_kit.utils.*` or remove the rows from
    the MIGRATION table.
- **P0** — `resilience_kit.metrics` exposes `MetricsSink` /
  `NoopMetricsSink` / `StdlibLoggingMetricsSink` / `get_metrics()` — a
  Protocol-based sink API. The boilerplate's `core.metrics` ships free
  functions `record_duration` / `record_counter` / `record_gauge` plus
  a runtime cardinality contract (`_assert_bounded`,
  `_BOUNDED_LABEL_KEYS`). Surfaces are incompatible; rewriting every
  caller (`middleware/metrics_middleware.py`, `utils/logging.py`,
  `tests/test_metrics_shim.py`) to the Protocol API would lose the
  bounded-label guard. **Keep** `core.metrics`; remove from Step 8
  delete list.
  - **Ask kit**: either ship a free-function shim or document the
    Protocol API as additive (not a replacement for project-level
    metrics modules).
- **PRAISE** — single-line bridge `class BaseCustomError(ResilienceKitError)`
  + composition wrapper in `handler.py` makes every domain exception
  simultaneously envelope-aware AND kit-aware. Zero subclass edits.
  Kit's flat `__init__(message, *, details)` signature composes
  cleanly with `BaseCustomError.__init__` calls already in place.
- **P1** — kit ships no `GlobalThrottle`. Boilerplate's local
  `class AuthThrottle(ValkeyRateThrottle)` parent is gone; rewrote it
  as `class AuthThrottle(rest_framework.throttling.AnonRateThrottle)`
  with scope `"auth"` and rate from `DEFAULT_THROTTLE_RATES["auth"]`.
  Loses Valkey-backed sliding window for that endpoint family —
  acceptable because the burst throttle (`AuthEndpointThrottle`) and
  nginx still provide layered defence.
- **P2** — kit `reset_all_singletons()` is **synchronous**
  (`() -> None`), not a coroutine. Logical given Django-sync tests; just
  surprised because the FastAPI adapter exposed an async equivalent.
  Doc could call out the sync/async parity.
- **PRAISE** — `resilience_kit.registry.register_service(name, overrides)`
  is a drop-in for the boilerplate's `register_resilience_service`;
  `core.registries.__init__` re-exports it as a bound method without
  any wrapper code. AppConfig.ready() flow stayed identical.

## Step 8 — Delete embedded modules + exceptions bridge (pending)

- **P0 (anticipated)** — kit's `ExternalServiceError` /
  `RepositoryError` / `ValidationError` / `RateLimitError` inherit from
  `ResilienceKitError`, not from the boilerplate's `BaseCustomError`.
  MIGRATION §2 "gut → re-export" doesn't work as-is — domain subclasses
  (`S3Exception`, `SESException`, `PartnerPushError`,
  `OutboundURLNotAllowedError`) need `BaseCustomError` for envelope
  rendering + `register_exception_mapping`.
  - **Plan**: bridge boilerplate-side via multiple inheritance:
    ```python
    class ExternalServiceError(_KitExternalServiceError, InfrastructureError): ...
    ```
    so domain subclasses are simultaneously `ResilienceKitError` and
    `BaseCustomError`.
  - **Ask kit**: document the multi-inheritance bridge in MIGRATION;
    or expose a `make_envelope_compatible(cls)` mixin.

## Step 9 — Tests (pending)

(notes added live)

## Step 10 — Push + PR (pending)

(notes added live)

---

## What the kit DOES NOT cover — boilerplate must retain

These were correctly carved out (per ROADMAP M7) but worth re-stating
so the audit report has the full picture:

- **Response envelopes** (`core.api_schemas`, `SuccessResponse`,
  `ErrorResponse`, `PaginatedResponse`). Out of scope per PRD §6.
  → Kit's `exception_handler.handle()` returns a kit-shape Response,
  not the envelope. Composition wrapper required.
- **ORM bases** (`BaseModel`, `NamedBaseModel`, `BaseService[T]`,
  `BaseRepository`, audit-field stamping, `bulk_create` validation).
  Boilerplate-owned. No kit surface.
- **api_log** (richer audit pipeline than kit's `audit.AuditEvent` —
  inbound + outbound request bodies, sanitisation, ORM backend).
  Different feature; both ship.
- **RBAC** (`core.permissions.HasResourcePermission`, `register_resource`,
  enums). Boilerplate-owned.
- **OpenAPI** (`drf-spectacular` metadata, error-envelope responses).
  Boilerplate-owned.
- **Authentication** (CompositeAuthentication, JWT, API key). Boilerplate-owned.

## Audit-report skeleton (for task #21)

```
docs/m7-kit-integration-report.md
├── Executive summary
├── What worked (praise — adapter shape, lifecycle, middleware split, …)
├── Gaps blocking documented migration path (P0)
├── Ergonomics / rough edges (P1)
├── Surface-area gaps vs. boilerplate features (response envelope,
│   ORM bases, api_log, exception envelope handler, GlobalThrottle, …)
├── Kit-side follow-up tickets (table: id / title / priority / context)
└── MIGRATION doc corrections
```
