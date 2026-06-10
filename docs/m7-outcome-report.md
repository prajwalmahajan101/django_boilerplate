# M7 outcome report — was depending on `resilience-kit` worth it?

> Companion to [`docs/m7-kit-integration-report.md`](./m7-kit-integration-report.md)
> (which graded the *journey*). This report grades the **outcome** —
> the shape of the codebase after migration, regardless of how it got
> there. Same answer either way: would I take this code over the
> previous code?
>
> Methodology: compare `main` (the pre-migration state at commit
> `3aa761f`) against `feat/depend-on-resilience-kit` HEAD (`1b19511`).
> All line counts come from `git ls-tree -r main` / `git diff
> --numstat main..HEAD`.

---

## 1. Numbers at a glance

| Metric | Before (`main`) | After (`HEAD`) | Δ |
|---|---:|---:|---:|
| Source lines (apps/ + config/) | baseline | baseline | **−3 550** |
| Test lines | baseline | baseline | **−746** |
| Test files | 43 | 31 | **−12** |
| Doc lines | baseline | baseline | **+732** |
| Files importing `resilience_kit` | 0 | 13 | +13 |
| Lockfile lines (4 layers) | baseline | baseline | +1 024 (transitive) |
| Direct `requirements/*.in` entries | `tenacity`, `pybreaker` | `resilience-kit[…]` | net −1 |

**Net code we own** (source + tests, excluding the running doc/notes):
**−4 296 lines**. The kit pulls those, plus a deeper transitive
dependency footprint (`pydantic-settings`, `pydantic`, `httpx`,
`asyncpg`, `cryptography`, `tenacity`, `pybreaker`) — visible to
auditors via the locks, invisible to the source tree.

### What the −3 550 source-line delta is made of

| Category | LOC at main | Status |
|---|---:|---|
| Circuit breakers / retry / decorators / registry / recovery / health | 1 415 | **gone** — kit owns |
| Throttles (Valkey + memory + DRF impl + Lua) | 1 140 | **gone** — kit owns (except `GlobalThrottle`, dropped) |
| Cache backends (Valkey + in-memory + provider chain) | 614 | **gone** — kit owns |
| HTTP client (aiohttp wrapper, SSRF guard, allow-list) | 584 | **gone** — zero external callers, kit ships `AsyncAPIClient` |
| Kit-owned middleware (6 files) | 351 | **gone** — kit owns |
| `utils/crypto` + `testing/reset` + `runtime` | 269 | **gone** — kit owns |
| | **4 373** | |

Plus the deleted tests (~1 033 lines across 12 files) that tested
those primitives. None of the contract was tested twice — that's pure
duplication eliminated.

### What we kept and didn't touch

The kit doesn't try to own these, and we didn't move them:

| Domain feature | LOC | Why it stayed |
|---|---:|---|
| `apps/core/api_log/` — inbound + outbound audit, sanitisers, ORM backend | 1 380 | Richer than kit's `audit.AuditEvent`; project-specific redaction guarantees. |
| `apps/core/base/` — `BaseModel`, `BaseService[T]`, `BaseRepository`, audit-field stamping | 1 288 | Pure domain ORM scaffolding. |
| `apps/core/exceptions/` — `BaseCustomError` + envelope-aware handler + domain subclasses | 917 | Now *bridged* to the kit's tree (one line); domain subclasses + envelope rendering stay here. |
| `apps/core/api_schemas/` — drf-spectacular metadata + envelope responses | 538 | Boilerplate-domain OpenAPI. |
| `apps/core/auth/` — composite auth, registry | 194 | Boilerplate-domain. |
| `apps/core/responses/` — `SuccessResponse`, `ErrorResponse`, `PaginatedResponse` | 147 | Boilerplate envelope contract. |
| `apps/core/permissions.py`, `rbac_registry.py` | 141 | RBAC. |
| `apps/core/utils/{log_sanitization,network,timing,function_logger,data,aws,db,filters,ses,s3,valkey,pagination,logging}.py` | ~900 | Mixed: some are domain (aws, ses, s3), some are kit-gap survivors (log_sanitization, network, timing) — kit ships no equivalents. |
| `apps/core/metrics.py` + `middleware/metrics_middleware.py` | 240 | Kit's Protocol API is incompatible with the bounded-label runtime contract. |
| `apps/core/lifecycle/healthcheck.py` | 138 | Django-specific DB/cache/Celery probes; kit's `health_snapshot` only covers kit-registered services. |
| `apps/core/middleware/{request_logging,throttling}.py` | ~160 | Boilerplate-specific structured logging + auth-burst throttle. |

That's a healthy split. The kit took the parts the boilerplate kept
re-implementing across projects; the parts that encode project-specific
opinions stayed put.

---

## 2. Wins

### 2.1 Less code we have to maintain

3 550 fewer source lines and 746 fewer test lines is real. The
boilerplate now has **zero** in-tree Valkey Lua scripts, **zero**
circuit-breaker state machines, **zero** custom rate-limit token
buckets, **zero** Fernet helpers. The 12 deleted test files were
re-implementing the kit's contract suite — strict duplication.

### 2.2 One source of truth across consumers

Two boilerplates (FastAPI + Django) and any third project that picks
the kit up share one implementation of:
- circuit breakers (`pybreaker` + Valkey fallback)
- retries with backoff + jitter
- the Fernet helper and the `EncryptedCharField` ORM column
- request-id ContextVar plumbing
- the security-headers middleware
- the SSRF guard (DNS-pinned, allow-list aware)
- the body-size cap
- the singleton-reset entry point for tests

That's the consolidation argument. Worth the migration on its own.

### 2.3 Lifecycle automation we no longer own

`ResilienceConfig.ready()` in the kit's Django adapter owns:
- spinning up the recovery-monitor daemon thread,
- driving the asyncio loop that the monitor needs,
- registering atexit cleanup with timeout,
- draining the audit dispatcher on shutdown,
- the autoreload double-start guard.

That's ~22 lines of subtle threading code the boilerplate used to ship
and now doesn't.

### 2.4 The exception bridge is, surprisingly, *better* than what we had

Before: `BaseCustomError(Exception)`. Project exceptions descended
from it; nothing else.

After: `BaseCustomError(ResilienceKitError)`. Every domain exception
is **also** a `ResilienceKitError`, which means:
- `@retry` and `@resilient` decorators (kit-side) can match on our
  `TransientError` / `ExternalTimeoutError` subclasses without us
  registering them anywhere;
- the kit's exception handler can fall back to envelope-shape if our
  handler ever fails to load;
- if we ship a kit-shaped microservice tomorrow, the same exception
  class works on both sides of the wire.

One-line change, three downstream benefits. Pure win.

### 2.5 The `EncryptedCharField` re-export is invisible

Django's autodetector does **not** flag the path change because the
re-export shields both the frozen migration and the in-memory model
through the same `core.base.fields.EncryptedCharField` import. Zero
migration churn, zero data migration risk. We expected to commit a
no-op AlterField; we didn't have to. Clean.

### 2.6 We can upgrade the kit without touching the boilerplate

`pip install --upgrade resilience-kit` will (eventually) ship breaker
backend improvements, throttle bug fixes, audit pipeline upgrades —
all without a boilerplate PR. That's the whole point of depending on
a library instead of vendoring it, and the migration finally
*actually* delivers it.

### 2.7 The middleware stack reads exactly the same

Before, after — the `MIDDLEWARE` list at `config/settings/base.py` has
the same 16 entries in the same order. The string paths changed; the
behaviour didn't. Five years from now, a new contributor reading the
list will understand it in the same time it took them on `main`.

---

## 3. Losses

These are real and they belong in this column. None of them was a
deal-breaker, but a fair report names them.

### 3.1 `GlobalThrottle` is gone

The boilerplate had a Valkey + Lua-backed in-process global cap
(`10 000/min` system-wide). The kit doesn't ship one. We dropped it
and now rely on nginx `limit_req` for the system-wide ceiling, which
is fine for the documented topology — but **a deployment without
nginx in front (laptop dev, single-pod deploy) lost a defence layer**.

Recoverable: file a kit-side ticket (KIT-M7-08 in the integration
report), port the Lua script back. Until then, this is a real loss
for anyone running without an L7 reverse proxy.

### 3.2 The cardinality guard for metrics is gone-ish

`apps/core/metrics.py` still exists, but its `_assert_bounded` runtime
check used to be the single enforcement point for label cardinality.
The kit's Protocol-based `MetricsSink` has no equivalent. Today the
guard is still active (we kept `core.metrics`), but the moment we
switch to kit metrics for any reason we lose it.

Recoverable: kit-side ticket to ship the bounded-label mixin
(KIT-M7-03). Until then, the boilerplate's metrics surface is a
boilerplate-private island.

### 3.3 The `RATE_LIMIT_*` / `CIRCUIT_BREAKER_*` / `FIELD_ENCRYPTION_KEY`
operator env vars stopped being authoritative

Deployments that pinned `RATE_LIMIT_ANON=200/hour` or
`FIELD_ENCRYPTION_KEY=…` directly will silently fall back to defaults
unless they update env files to the `RESILIENCE_*` shape. We didn't
ship a compatibility shim — there's a real ops-side migration burden
hidden in step 2.

Recoverable but **not free**: deployment env files need a manual
audit before promoting this branch past staging. The release notes
must call this out loudly.

### 3.4 `apps/core/utils/http_client/` is gone with no callers

This is technically a win (584 lines deleted, no callers to break),
but worth naming: the boilerplate now has **no in-tree HTTP client**
beyond `requests` + the kit's `AsyncAPIClient` (which is httpx-based,
not aiohttp). If we ever want to make outbound HTTP calls again, the
choice is "use the kit's httpx wrapper" or "build a new one." The
aiohttp-flavoured wrapper is gone.

Probably the right call (aiohttp + Django sync isn't a happy mix), but
we lost the option without making a decision.

### 3.5 The `RESILIENCE` dict in `config/settings/base.py` is mostly cosmetic

Step 2 put a beautiful nested `RESILIENCE` dict in `base.py`. The kit
reads exactly one key out of it (`services`). The rest is a comment in
Python-dict shape. Anyone editing that dict expecting it to *do*
something will be surprised.

Recoverable: kit-side ticket (KIT-M7-01, ship a real
`DjangoSettingsSource`), at which point the dict goes live for real.
Until then, the visible config story is half a story.

### 3.6 The bridge is a load-bearing line of code with no test

`class BaseCustomError(ResilienceKitError)` is one line. It's the line
that makes every domain exception envelope-aware *and* kit-aware. If
someone removes it ("looks redundant?"), the kit handler will start
catching domain exceptions and break the envelope, and the
`with_details` / `details` property collision will resurface.

We didn't ship a test that pins this invariant. Should. Cheap follow-up.

### 3.7 We import slightly more on cold start

The kit's adapter pulls `pydantic`, `pydantic-settings`,
`pydantic-core`, `httpx`, `asyncpg`, `cryptography`, and friends at
`INSTALLED_APPS` resolution time. Locally on a warm cache this is
imperceptible; on a cold deploy or `manage.py shell` it's measurably
slower than the embedded code was. Single-digit hundreds of
milliseconds, not seconds — but it's not zero.

---

## 4. Better to have (would tip the scale further)

These aren't losses — they're things that, if shipped, would convert
"this was a net win" into "this was an obvious win in retrospect".

1. **A real `DjangoSettingsSource`.** Make the `RESILIENCE` dict
   load-bearing so consumers don't have to write env vars to control
   the kit. The single highest-leverage doc + code change the kit can
   ship next.
2. **`resilience_kit.utils.{log_sanitization, network, timing,
   function_logger, data}`.** These are five tiny modules that every
   project re-implements. Shipping them moves another ~900 lines out
   of the boilerplate.
3. **A `GlobalThrottle`.** Port the Lua script. Restores the in-process
   defence layer we lost. Maybe an afternoon's work kit-side.
4. **The exception bridge documented in the MIGRATION doc.** The
   bridge worked beautifully but we discovered it on the fly. Saving
   the next consumer that discovery is a five-paragraph doc edit.
5. **A `verify_envelope_contract()` test helper.** A kit-side fixture
   that asserts "given your project's `EXCEPTION_HANDLER`, raising
   each `ResilienceKitError` subclass returns your envelope shape".
   Would have caught the `details` property collision in CI, before
   anyone got to the migration.
6. **A `legacy_env_alias()` translator.** Ship `RATE_LIMIT_*` →
   `RESILIENCE_DEFAULTS__THROTTLE__*` aliases (or a function projects
   import once in `settings/base.py`). Removes the operator surprise
   from §3.3.
7. **A free-function metrics shim.** `from resilience_kit.metrics
   import record_duration, record_counter, record_gauge` over the
   Protocol sink. Lets projects keep their call sites and tee into the
   kit's pluggable backend.
8. **An ADR template for "depending on the kit".** Recording the
   bridge decision, the composition decision, the env-var translation
   pattern, and the `RESILIENCE` dict caveat in `docs/adr/0009-…md`
   would future-proof this PR against the next person who reads
   `settings/base.py` and wonders why `RESILIENCE` "doesn't work".

---

## 5. Rating

> Premise the user named: ignore how painful or smooth the migration
> was. Look at what the previous code was, what the new code is, and
> decide.

**Code shape: 9 / 10.** We deleted ~3 550 lines of carefully-tested
infrastructure and lost almost nothing real. The pieces we kept are
exactly the pieces that *should* stay project-side. The bridge that
unifies the exception trees is genuinely better than what was there.
The middleware order, the throttle classes, the `EncryptedCharField`
import — they all read the same as before, with stronger backing.
The one point off is for `GlobalThrottle` (a real capability loss for
non-nginx topologies) and the dead `RESILIENCE` dict body (which
honestly looks like config but isn't).

**Operational story: 7 / 10.** `migrate --check` clean, `manage.py
check` clean, 171 tests pass. But the env-var contract changed
silently — any deploy that didn't update env files lost tuning. The
crypto-fallback default is now hostile to local/test in a way the old
code wasn't. The lockfile grew by 1 024 lines of transitive deps, all
of which need ongoing pip-audit coverage.

**Dependency health: 8 / 10.** Net we own less code, and what we
depend on is now a published, semver'd PyPI package with its own test
suite. The kit pulls a deeper transitive tree (`pydantic-settings`,
`httpx`, `asyncpg`) but every one of those is a well-maintained
upstream — exactly the trade we want to make. One point off for the
`0.1.0rc1` pin: depending on an rc has version-stability cost until
M8 ships.

**Architectural fit: 9 / 10.** The kit took the right slice. It owns
the cross-cutting infrastructure (breakers, retries, throttles,
middleware, SSRF, Fernet, audit primitives). The boilerplate owns the
domain layer (envelopes, ORM bases, RBAC, OpenAPI, auth, api_log).
The bridge between them is one line in `BaseCustomError`. That's a
clean architectural seam, not a leaky one. The −1 is because the
metrics surface didn't land in either column — it's neither
kit-owned nor cleanly project-owned.

**Future maintainability: 9 / 10.** The kit publishes; we upgrade by
bumping a pin. No more "the breaker is wrong in fastapi_boilerplate
but right here" branch drift. The composition + bridge pattern is
explicit and discoverable in `handler.py` and `base/exception.py`. The
docs we wrote during the migration (`m7-kit-integration-notes.md`,
`m7-kit-integration-report.md`) capture the rationale so the next
maintainer doesn't have to rediscover any of it. One point off for the
unprotected bridge line (§3.6).

### Composite

**8.4 / 10** weighted equally; **8.6 / 10** weighting code shape and
architectural fit higher.

Either way: this was worth doing.

---

## 6. The honest verdict

The pre-migration code was *good* — the boilerplate's resilience tree
was carefully built, well-tested, and a textbook example of doing the
work properly in-tree. The migration didn't replace bad code with
good code; it replaced **good code we owned with good code someone
else owns**. The question is whether the someone-else-owns-it part is
worth the migration cost.

For this repo, yes. The shared kit is the right home for breakers,
throttles, middleware, and Fernet — they don't encode anything
boilerplate-specific. Splitting them out frees the boilerplate to be
about *application bootstrapping* (auth, RBAC, ORM, OpenAPI, audit,
envelope shape) rather than *infrastructure plumbing*. That's a
sharper identity, and a sharper identity ages better.

If the kit ships even half of the §4 "better to have" list before M8
locks in `0.1.0`, this will read like an obviously-correct decision a
year from now. If it ships none of them, this will still read like a
defensible decision — just one with three known sharp edges
(`GlobalThrottle`, env-var translation, the dead `RESILIENCE` dict)
that future maintenance has to step around.

I'd take this branch.
