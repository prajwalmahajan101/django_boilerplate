# resilience-kit 0.1.0rc1 — Django boilerplate integration report

> **Subject:** `django_boilerplate` ← `resilience-kit==0.1.0rc1` (M7 phase 3).
> **Author:** the dev who ran the migration end-to-end (10 atomic commits on
> `feat/depend-on-resilience-kit`, 171 tests passing, app boots clean).
> **Audience:** the kit maintainer.
> **Goal:** turn one project's lived-in pain into a prioritised
> punch-list the kit team can ship against, alongside the design
> choices that already worked.
>
> Source notes live in [`docs/m7-kit-integration-notes.md`](./m7-kit-integration-notes.md)
> (captured per-step during the migration, not reconstructed).

---

## 1. Executive summary

The kit is **shippable** for projects that build on top of it green-field
or for repos willing to do a thoughtful refactor. It is **not yet a
drop-in** for the boilerplate the MIGRATION doc was written against —
five documented paths failed in load-bearing ways and required local
workarounds.

The good news: the kit's lifecycle, decorator surface, middleware
classes, throttles, `EncryptedCharField` re-export, and singleton-reset
helper all worked first try and **shrank the boilerplate by ~4 400
lines** without losing behaviour. The bad news: the
`settings.RESILIENCE` config story, the `resilience_kit.utils.*`
sub-package, the metrics surface, the exception ancestry, and the
`GlobalThrottle` are gaps the MIGRATION doc told us to expect but the
shipped wheel does not honour. Workarounds exist for every one; none
of them required holding the migration.

The bridge-and-compose pattern we settled on
(`BaseCustomError → ResilienceKitError` + composed DRF handler) is, in
hindsight, the architecture the MIGRATION doc *should* have described
in the first place. We strongly recommend folding it into the next doc
revision so the next downstream consumer doesn't rediscover it.

---

## 2. What the kit got right (praise)

These are the design choices that paid off during the migration.
Recording them so they survive across refactors.

- **Adapter `AppConfig` is the right shape.** One line in
  `INSTALLED_APPS` and the recovery monitor, audit dispatcher, atexit
  drain, and autoreload guard all came for free. The boilerplate
  shipped 22 lines of `_start_recovery_monitor` + atexit + threading
  guard. Now those 22 lines are gone and the lifecycle is identical.
- **Middleware names + semantics match the boilerplate's.** Five of
  six kit middleware were drop-in by *string* — `MIDDLEWARE` is the
  only file that changed, no view changes, no `RequestId` ContextVar
  bridging. The one rename (`SelectiveCorsMiddleware` lowercase `s`)
  is trivial.
- **`registry.register_service(name, overrides)` is a true drop-in.**
  `core.registries.register_resilience_service` became a bound-method
  re-export with zero shim code. Domain `AppConfig.ready()`
  registrations need no change.
- **`testing.reset.reset_all_singletons()` covers everything.** Every
  singleton the boilerplate's hand-rolled `core.testing.reset` touched
  is covered. Tests didn't need any custom reset hook after the swap.
- **`EncryptedCharField` re-export survives Django's autodetector.**
  No-op migration NOT generated — both the frozen migration's
  `core.base.fields.EncryptedCharField` path and the new in-memory
  model path resolve through the re-export to the same kit class.
  Surprising and excellent.
- **The single-point exception bridge composes cleanly.**
  `ResilienceKitError.__init__(message, *, details=None)` happens to
  be a perfect superset of `BaseCustomError.__init__(message, *,
  status_code=None)` — one base-class swap on `BaseCustomError`
  promoted every domain exception to a kit exception with zero
  subclass edits.
- **PyPI release worked.** `pip install
  resilience-kit[django,redis,http,crypto,audit-postgres]==0.1.0rc1`
  resolved cleanly and `pip-compile --generate-hashes` produced
  reproducible locks. (Note: the MIGRATION doc still references the
  `git+ssh://…@milestone/m7-rc1` pin — fix below.)
- **`./manage.py check` and `migrate --check` both went green** with no
  intermediate scaffolding. The kit ships clean for Django's startup
  invariants.

---

## 3. Surface-area gaps vs. the boilerplate

The kit deliberately stays out of these by design (PRD §6).
Recording them so the audit picture is complete — these are *not*
asks, just statements of scope:

| Boilerplate-owned surface | Kit equivalent? | Notes |
|---|---|---|
| Response envelopes (`SuccessResponse`, `ErrorResponse`, `PaginatedResponse`) | No (intentional) | Kit's `exception_handler.handle` returns its own shape, hence the composition wrapper. |
| ORM bases (`BaseModel`, `NamedBaseModel`, `BaseService[T]`, `BaseRepository`, audit-field stamping, `bulk_create` validation) | No (intentional) | Pure boilerplate domain. |
| `api_log` (rich inbound + outbound audit with sanitisers, ORM backend) | Partial — kit ships `AuditEvent` + `log_inbound/log_outbound` + simple backends, but the boilerplate's pipeline (fire-and-forget dispatch, request-body redaction guarantees, ORM persistence) is richer | Kept boilerplate's `apps/core/api_log/` end-to-end. |
| RBAC (`HasResourcePermission`, enum registry, role/permission models) | No (intentional) | Boilerplate domain. |
| OpenAPI / `drf-spectacular` metadata | No (intentional) | Boilerplate domain. |
| Authentication (CompositeAuthentication, JWT, API key) | No (intentional) | Boilerplate domain. |
| Domain exception subclasses (`S3Exception`, `SESException`, `PartnerPushError`, `OutboundURLNotAllowedError`, `EntityNotFoundError`, …) | No (intentional, but see §4 bridge) | These compose ON TOP of the kit's primitives via bridge. |

Everything in this table is correctly scoped per the PRD. We're not
asking the kit to grow into any of these.

---

## 4. Gaps blocking the documented migration path (P0)

Every item here is something the MIGRATION doc told us to expect that
the shipped wheel doesn't deliver. Workarounds exist, but each one is
a paper-cut for the next downstream consumer.

### 4.1 `DjangoSettingsSource` doesn't actually read `settings.RESILIENCE`

**Doc claim** (MIGRATION §3, "Django: settings.RESILIENCE dict"):

> Django's `DjangoSettingsSource` reads `settings.RESILIENCE` (mirroring
> the env shape).

**Reality** (verified — `resilience_kit/adapters/django/apps.py:64-74`):

```python
services: Mapping[str, Mapping[str, Any]] = getattr(
    django_settings, "RESILIENCE", {},
).get("services", {})
for name, overrides in services.items():
    registry.register_service(name, overrides)
```

Only the `"services"` key is read. Every other key (`backend`,
`redis_url`, `defaults`, `ssrf`, `crypto`, `audit`,
`rate_limit_headers`) is silently ignored. The kit reads them from
`RESILIENCE_*` env vars via pydantic-settings — a different,
incompatible, non-documented contract.

**Impact**:
- Operationally surprising: `settings.RESILIENCE["crypto"]["field_encryption_key"]`
  has no effect. Projects that follow MIGRATION §3 verbatim ship
  silently-broken config.
- Forces a translation layer in `settings/base.py` to convert legacy
  env names (`RATE_LIMIT_ANON`, `CIRCUIT_BREAKER_FAIL_OPEN`,
  `FIELD_ENCRYPTION_KEY`) into `RESILIENCE_*` form before pydantic
  reads them.

**Ask**: ship a real `DjangoSettingsSource` that flattens
`settings.RESILIENCE` into the env-prefix shape pydantic expects;
register it via `ResilienceConfig.ready()` so projects can choose
between Django-native config and env-only.

### 4.2 `resilience_kit.utils.*` sub-package is missing

**Doc claim** (MIGRATION §2 deletion table):

> `core/utils/{log_sanitization,function_logger,network,timing,data}.py`
> — delete → `from resilience_kit.utils.{…} import …`

**Reality**: `ModuleNotFoundError: No module named 'resilience_kit.utils'`.

**Impact**: boilerplate kept all five files. Step 8's deletion sweep
shrunk by ~900 lines vs. the doc's promise. Not a blocker — these are
small, stable, project-domain helpers — but the doc claim is false.

**Ask**: either ship `resilience_kit.utils.*` (recommended — these
*are* genuinely reusable across consumers) or drop those rows from the
MIGRATION table.

### 4.3 `resilience_kit.metrics` is a Protocol API, not a free-function shim

**What the boilerplate has**: free functions
`record_duration(metric, ...)`, `record_counter`, `record_gauge` plus
a runtime cardinality contract (`_BOUNDED_LABEL_KEYS`,
`_assert_bounded`) that prevents unbounded-label drift at observability
time.

**What the kit ships**: `MetricsSink` / `NoopMetricsSink` /
`StdlibLoggingMetricsSink` / `get_metrics()` — a Protocol-based
sink-object pattern, no cardinality guard.

**Impact**: rewriting every caller (`middleware/metrics_middleware`,
`utils/logging.log_duration`, every domain `log_duration(metric=...)`
call site) to the Protocol API would lose the bounded-label runtime
check. Kept `apps/core/metrics.py`; not deleted.

**Ask**: ship a `resilience_kit.metrics.record_duration` /
`record_counter` / `record_gauge` free-function shim layered on top of
the Protocol sink. Position the Protocol API as the *backend* contract,
not the *caller* contract. Optionally: ship the bounded-label guard as
a configurable mixin.

### 4.4 Crypto refuses fallback in `environment=prod` (the default)

**What broke**: in test settings without a Fernet key explicitly
configured, the first fixture that touches `EncryptedCharField` blows
up with `EncryptionConfigError: field_encryption_key must be set when
settings.crypto.environment='prod'`. The boilerplate's old path
warned-and-fell-back to `SECRET_KEY`.

**Workaround**: set `RESILIENCE_CRYPTO__ENVIRONMENT=dev` and a
deterministic test-only Fernet key in `config/settings/test.py`.
Documented in the test settings file inline.

**Ask**: ship a `crypto.allow_secret_key_fallback` flag (off by default,
opt-in for local/dev) or a kit-provided pytest fixture that
auto-supplies a deterministic key when `environment=dev`. Update
MIGRATION §6 to flag the breaking change explicitly.

### 4.5 DRF `EXCEPTION_HANDLER` swap breaks the envelope contract

**Doc claim** (MIGRATION §5, after diff):

```python
"EXCEPTION_HANDLER": "resilience_kit.adapters.django.exception_handler.handle"
```

**Reality**: this points DRF at a handler that only catches
`ResilienceKitError` and defers everything else to DRF's flat
`{detail: "..."}` shape. Any project that uses a wrapped error
envelope (status + message + errors[] + request_id) breaks the moment
a domain `BaseCustomError` is raised.

**Workaround**: keep `EXCEPTION_HANDLER` pointed at the boilerplate's
handler, compose the kit handler *inside* it (kit-first for raw kit
exceptions, envelope renderer for everything else). Combined with the
exception bridge (§5 below) this is the right pattern for any project
with a custom error envelope.

**Ask**: document the composition pattern in MIGRATION §5; consider
exposing `kit.handle` as a *helper* the project handler can call rather
than as the documented `EXCEPTION_HANDLER` target.

---

## 5. Ergonomics / rough edges (P1)

### 5.1 Exception hierarchies don't share a base; need a bridge

The kit's `ResilienceKitError` and the boilerplate's `BaseCustomError`
are independent trees. Any project that ships an envelope renderer
needs to bridge them — we did it with `class
BaseCustomError(ResilienceKitError)`. Worked perfectly, but the
MIGRATION doc didn't mention it.

The fix is one line of project code, but it's a critical line; the
next consumer will rediscover it. Recommend the MIGRATION doc grow a
§2.5 *"Bridging your exception hierarchy"* section.

### 5.2 `ResilienceKitError.details` is a read-only `@property`

`@property` (backed by `_details`) collides with any subclass that
does `self.details = ...`. The boilerplate's `ValidationError` hit it
immediately. Fixed by shadowing on `BaseCustomError`:

```python
class BaseCustomError(ResilienceKitError):
    details: Any = None  # frees the name for subclass __init__ assignment
```

**Ask**: relax `details` to a normal instance attribute with
`with_details()` staying as the canonical mutator, OR document the
collision in MIGRATION.

### 5.3 No `GlobalThrottle`

Kit ships `IP/UserTier/Burst/Endpoint/Auth`. The boilerplate had a
Valkey + Lua-backed process-wide cap (`GlobalThrottle`,
~10 000/min). Dropped during migration; nginx `limit_req` continues to
provide the system-wide ceiling so the loss is recoverable.

**Ask**: port the boilerplate's `GlobalThrottle` (Lua script was at
`apps/core/resilience/throttles/global_lua.py`). It's a well-trodden
production pattern; one more class on the kit's surface keeps in-process
defence-in-depth with nginx.

### 5.4 Env-var contract isn't backward-compatible

Boilerplate's existing operational env names:
`RATE_LIMIT_ANON`, `CIRCUIT_BREAKER_FAIL_OPEN`, `FIELD_ENCRYPTION_KEY`.

Kit's names:
`RESILIENCE_DEFAULTS__THROTTLE__ANON_RATE`,
`RESILIENCE_FAIL_OPEN`,
`RESILIENCE_CRYPTO__FIELD_ENCRYPTION_KEY`.

Any deploy that doesn't update env files silently loses tuning.

**Ask**: alias the legacy names, or ship a documented
`legacy_env_translator()` snippet projects can paste into their
settings module. Prefer aliasing — it's invisible to consumers.

### 5.5 `register_service(..., excluded_exceptions=("…",))` takes strings

Works, but cross-package string refs are fragile under renames. The
boilerplate's S3 exclusion now uses
`"core.exceptions.infrastructure.S3NotFoundError"` (boilerplate-side
string) while the rest of the resilience config lives kit-side.

**Ask**: accept exception **classes** in addition to strings; document
the resolution order. A `Union[type[BaseException], str]` annotation
is enough.

---

## 6. Minor / polish (P2)

- MIGRATION doc still references `git+ssh://…@milestone/m7-rc1` pin —
  PyPI release exists, fix the doc.
- `SelectiveCorsMiddleware` lowercase `s` vs. boilerplate's
  `SelectiveCORSMiddleware`. Minor; just a string.
- `reset_all_singletons()` is sync (`() -> None`), not a coroutine.
  Fine in Django; surprising after the FastAPI side. One line in the
  reset module docstring would clarify the sync/async parity.

---

## 7. Prioritised follow-up tickets

| ID | Title | Pri | Section | Effort |
|---|---|---|---|---|
| KIT-M7-01 | Ship `DjangoSettingsSource` that reads `settings.RESILIENCE` | P0 | §4.1 | M |
| KIT-M7-02 | Ship `resilience_kit.utils.{log_sanitization,network,timing,function_logger,data}` OR remove from MIGRATION table | P0 | §4.2 | S–M |
| KIT-M7-03 | Add free-function shim `metrics.{record_duration,record_counter,record_gauge}` over the Protocol sink | P0 | §4.3 | S |
| KIT-M7-04 | Crypto: opt-in `allow_secret_key_fallback` flag + dev fixture | P0 | §4.4 | S |
| KIT-M7-05 | Document the composition pattern for DRF `EXCEPTION_HANDLER` | P0 | §4.5 | S (docs) |
| KIT-M7-06 | MIGRATION §2.5 — "Bridging your exception hierarchy" | P0 | §5.1 | S (docs) |
| KIT-M7-07 | `ResilienceKitError.details` — drop `@property`, keep `with_details()` | P1 | §5.2 | S |
| KIT-M7-08 | Ship `GlobalThrottle` (port boilerplate's Lua impl) | P1 | §5.3 | M |
| KIT-M7-09 | Legacy env-var aliasing | P1 | §5.4 | S |
| KIT-M7-10 | `register_service(excluded_exceptions=...)` — accept classes | P1 | §5.5 | XS |
| KIT-M7-11 | MIGRATION doc — flip git pin to PyPI pin | P2 | §6 | XS (docs) |
| KIT-M7-12 | Rename `SelectiveCorsMiddleware` → `SelectiveCORSMiddleware` (or both) | P2 | §6 | XS |
| KIT-M7-13 | Document sync vs async `reset_all_singletons()` parity | P2 | §6 | XS (docs) |

Effort key: XS < 1h · S < 4h · M < 2d · L < 1w.

---

## 8. MIGRATION doc corrections

Concrete edits to
`resilience-kit/docs/MIGRATION-from-boilerplate-embedded.md` discovered
during the integration:

1. **§1 (Install)** — replace the `git+ssh://…@milestone/m7-rc1` pin
   examples with `resilience-kit[…]==0.1.0rc1` (PyPI). Add a note that
   `0.1.0` flips at M8.
2. **§2 (Deletion table)** — `core/utils/{log_sanitization,
   function_logger,network,timing,data}.py` row currently says "delete
   → `from resilience_kit.utils.{…} import …`". Until §4.2 ships,
   change to "keep — kit ships no equivalent yet".
3. **§2 (Deletion table)** — `core/metrics.py` row says "delete →
   `from resilience_kit.metrics import MetricsSink`". The shapes don't
   compose. Change to "keep — kit's Protocol API is additive, not a
   replacement" pending §4.3.
4. **§2 (Django carve-outs)** — `apps/core/lifecycle/healthcheck.py`
   says "delete (mounted by adapter at `/readyz`)". The boilerplate's
   healthcheck is Django-specific (DB / cache / Celery probes); kit's
   `health_snapshot` only covers kit-registered services. Change to
   "**keep**; retarget `attempt_recover_all` import to
   `resilience_kit.recovery`".
5. **§3 (Settings translation)** — until §4.1 ships, replace the
   `settings.RESILIENCE` Django-dict example with the env-var
   translator pattern projects actually need.
6. **§5 (DRF diff)** — add the composition pattern for
   `EXCEPTION_HANDLER`. The literal swap is wrong for any project that
   ships an envelope.
7. **NEW §2.5 — "Bridging your exception hierarchy"** — describe the
   `class BaseCustomError(ResilienceKitError)` bridge + the
   `details` property collision + the
   `EXCEPTION_HANDLER` composition wrapper together. They're the
   architecture of the whole exception story.
8. **§6 (EncryptedCharField)** — Django autodetector typically does
   NOT need a no-op migration (verified — the re-export shields the
   path). Update "usually yes" → "usually no, but verify with
   `MigrationAutodetector`".
9. **§7 (Test-suite delta)** — flag the
   `RESILIENCE_CRYPTO__ENVIRONMENT=dev` requirement at the top of the
   section, not buried under a "common gotcha".
10. **§9 (Gotchas)** — add the three pre-existing-isn't-the-kit's-fault
    failures we hit (auth-registry MagicMock interaction, etc.) as a
    note: "the migration breaks no tests — but verify against `main`
    HEAD first to filter pre-existing failures".

---

## 9. What got measured

- **Commits**: 10 atomic on `feat/depend-on-resilience-kit`.
- **Lines deleted**: ~4 400 (kit-owned tree + tests).
- **Lines added**: ~440 (settings, bridge, composition, kit-gap notes,
  this report skeleton).
- **Tests**: 171 passing / 174 collected (3 pre-existing failures
  reproduce on `main`).
- **Migrations generated**: 0.
- **Time to first booting branch**: ~6 commits in (about half of
  total).
- **Architectural decisions surfaced via questions to the owner**: 2
  (handler strategy + exception-tree reconciliation).

The bridge + composition decision is by far the highest-leverage piece
of work in this PR; it's also the piece the MIGRATION doc was silent
about. If the doc grows just the new §2.5 in the next revision, the
next consumer's migration should be ~50% faster than this one.
