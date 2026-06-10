# resilience-kit `0.1.0rc1` → `0.1.0` migration report

- **Project:** `django_boilerplate`
- **Date:** 2026-06-11
- **Pin moved:** `==0.1.0rc1` → `==0.1.0`
- **Branch / PR:** `feat/depend-on-resilience-kit` (18 commits ahead of `main`; M7 phase 3 + M8 upgrade landed as a single PR — rc1 was never merged so we folded the upgrade into the same branch rather than stacking)

## Outcome score (1-10)

**Score: 9 / 10.** Every documented blocker had a one-helper fix that
worked first try; the four kit helpers (`legacy_env_alias`, `bind_to`,
`from_exception`, `verify_envelope_contract`) shipped in v0.1.0 are
precisely the helpers the M7 dogfooding audit asked for, in the shape
the audit recommended. The one point off is for the pre-existing lint
debt the rc1 work bypassed with `--no-verify` — surfaced loudly on first
pre-commit run but unrelated to the kit. End-to-end smoke test shows
`request_id` flowing kit → bridge → envelope (the same UUID appears in
the `X-Request-Id` response header and the JSON envelope's `request_id`
field), proof the B1 fix actually works in production middleware order.

## Blockers hit and resolved

- [x] **B1 — `request_id` null in our context layer.**
  - Resolved by: **`bind_to(target)`** wrapped in a thin
    `BindRequestIdMiddleware` (`apps/core/middleware/bind_request_id.py`)
    slotted in `MIDDLEWARE` immediately after the kit's
    `RequestIdMiddleware`. The kit writes to
    `resilience_kit.context.request_id`; our context manager mirrors
    that value into `core.context.request_id_ctx` for the duration of
    the request. ``BaseCustomError``, ``RequestContextFilter``, the
    DRF envelope handler — every project read site — picks up the
    same UUID downstream.
  - **Smoke proof:** ``GET /api/accounts/me/`` (anonymous, 401)
    returns envelope body
    ``{"request_id":"1e43827d5faa4fcfa3551acfcf9caa27", …}`` matching
    the response header ``X-Request-Id: 1e43827d5faa4fcfa3551acfcf9caa27``.
    rc1 returned ``"request_id":null``.

- [x] **B2 — two exception envelopes on the same app.**
  - Resolved by: **`from_exception(envelope_cls=ResponseEnvelope)`**
    inside the boilerplate's existing DRF handler
    (`apps/core/exceptions/handler.py`). The raw-`ResilienceKitError`
    branch — previously calling the kit's `handle()` and returning the
    kit-shape `{error_code, message, details}` — now projects the
    exception through the pydantic schema at
    `core.responses.envelope_schema.ResponseEnvelope`. Headers from
    `from_exception` (`Retry-After`, `X-RateLimit-*`) flow through to
    the DRF Response unchanged.
  - `REST_FRAMEWORK["EXCEPTION_HANDLER"]` stays pointed at the
    boilerplate's `api_exception_handler` per the brief.

- [x] **D-Env — legacy env-var names silently dropped tuning.**
  - Resolved by: **`legacy_env_alias()`** called at the very top of
    `config/settings/base.py` before any pydantic-settings
    instantiation. Verified: ``RATE_LIMIT_AUTH=99/min`` set in
    `os.environ` → kit reads
    ``RESILIENCE_DEFAULTS__THROTTLE__AUTH_RATE=99/min`` →
    ``DeprecationWarning`` emitted pointing at the rename. Operators
    see the signal on first staging deploy.
  - **Runbook caveat:** still recommended to hand-audit `.env*` and
    helm values files using kit's
    `MIGRATION-from-boilerplate-embedded.md` §10.5 table; the helper
    is opt-in and only translates the `DEFAULT_ALIASES` table.
    Project-specific env names that diverge from the boilerplate set
    need a hand pass.

- [x] **Django §3.6 — untested exception-bridge invariant.**
  - Resolved by: **`verify_envelope_contract`** in a single test at
    `apps/core/tests/test_envelope_contract.py`. The kit enumerates
    every public `ResilienceKitError` subclass (9 today), routes each
    through `api_exception_handler`, validates the result against
    `ResponseEnvelope.model_validate`, and collects every failure
    into one `AssertionError`. A future kit release adding an
    exception class fails this test until the bridge accommodates it.

- [x] **(Bonus, surfaced during smoke)** The legacy
  `FIELD_ENCRYPTION_KEY → SECRET_KEY` fallback in
  `core.base.fields.EncryptedCharField` (gone in v0.1.0 by ADR-0008)
  is documented as a hard fail in `environment/.env.example`.
  Test/local environments pin `RESILIENCE_CRYPTO__ENVIRONMENT=dev`
  plus a deterministic Fernet key (already in test.py from rc1
  commit `a3a1a32`); production envs MUST set the
  `RESILIENCE_CRYPTO__FIELD_ENCRYPTION_KEY` env var or the kit
  refuses to encrypt.

## Helpers used

- [x] `resilience_kit.context.bind_to`
- [x] `resilience_kit.adapters._envelope.from_exception`
- [x] `resilience_kit.runtime.legacy_env_alias`
- [x] `resilience_kit.testing.verify_envelope_contract`
- [ ] `resilience_kit.testing.reset_all_singletons_async` — **considered, deferred.**
  `tests/conftest.py` is sync (pytest-django on Django sync); no
  async tests today. The sync `reset_all_singletons()` is fine for
  this topology. Worth flipping if/when we add `pytest-asyncio` tests.

## Missing surface (kit wishlist)

Restating from `docs/m7-kit-integration-report.md` §4–§5 — the M8
upgrade closed the four named blockers and uncovered no new
surface-level gaps, but the v0.2 wishlist from M7 still applies:

- **A real `DjangoSettingsSource`.** The `RESILIENCE` dict in
  `config/settings/base.py` is still mostly cosmetic — the kit's
  `ResilienceConfig.ready()` only reads `RESILIENCE["services"]`
  out of it. Everything else flows through env vars (and now through
  `legacy_env_alias`). Closing this gap turns the dict into the
  authoritative knob the MIGRATION doc promised.
- **`resilience_kit.utils.*`** — five small modules
  (`log_sanitization`, `network`, `timing`, `function_logger`,
  `data`) the boilerplate kept locally because the kit didn't ship
  them. Cross-project boilerplate that every consumer rewrites.
- **`GlobalThrottle`.** Dropped during rc1 because the kit shipped
  IP/UserTier/Burst/Endpoint/Auth but not a process-wide cap. Nginx
  `limit_req` covers it for our deployment topology but the
  in-process belt remains absent for laptop dev / single-pod deploys.
- **Free-function metrics shim.** Kit's Protocol `MetricsSink` API is
  incompatible with the boilerplate's `core.metrics` free-function
  surface + bounded-label cardinality guard. We kept `core.metrics`
  rather than rewrite ~5 callers + lose the guard. A
  `record_duration` / `record_counter` / `record_gauge` shim layered
  over `MetricsSink` would close the gap.
- **`ResilienceKitError.details` as instance attribute, not property.**
  The bridge in `BaseCustomError` had to shadow the kit's
  `@property details` so `ValidationError.__init__` could keep its
  existing `self.details = ...` pattern. Cheap win.

## Time spent per phase

Approximate, drawn from commit timestamps on the branch:

| Phase | Duration | Notes |
|---|---|---|
| Reading MIGRATION-rc1-to-v0.1.0.md + Appendix B | ~10 min | Including `WebFetch` of kit repo, local read of §10.5 mapping |
| Probing helper signatures vs documented behaviour | ~10 min | `inspect.signature` on each helper, smoke `from_exception` shape |
| Commits 1–5 (pin + 4 helpers) | ~25 min | Mostly mechanical once signatures verified |
| Pre-commit cleanup (auto-format + dead-utils allowlist) | ~10 min | Pre-existing lint debt surfaced from rc1's `--no-verify` history |
| Verification (pytest + check + migrate + smoke) | ~10 min | docker-compose `db` already running from earlier session |
| Writing this report | ~15 min | |
| **Total** | **~80 min** | Single session, no context switches |

## Doc gaps

`MIGRATION-rc1-to-v0.1.0.md` was tight and accurate. Three small
gaps surfaced during application:

1. **Appendix B should ship the Django-specific
   `BindRequestIdMiddleware` snippet.** §3.1 gives the FastAPI
   middleware shape; Django needs a 4-line equivalent class.
   We wrote it; should ship in the doc verbatim for the next
   Django consumer.
2. **§3.3 should call out that `legacy_env_alias()` ordering is
   load-bearing.** The helper must run *before* the kit's
   `ResilienceConfig.ready()` reads env at AppConfig boot — that
   means top of `settings/base.py`, not "anywhere in the file". We
   inferred it from `pydantic-settings` semantics, but a one-line
   explicit warning in §3.3 would save the next reader the lookup.
3. **§3.6's `verify_envelope_contract` example uses
   `handler(request=None, exc=exc).body`** — that's a FastAPI shape.
   For DRF the call returns a DRF `Response` whose dict is at
   `.data`, not `.body`. We adapted with a lambda; doc should show
   the DRF shape in Appendix B (same place the
   `BindRequestIdMiddleware` snippet would land).

## Pain points

Nothing kit-side. Two boilerplate-side observations worth flagging:

1. **Pre-commit had never run cleanly on this branch.** The rc1
   commits used `--no-verify` solely to dodge the project's
   `pip-compile-base` hook (which omits `--generate-hashes` and
   would strip our lockfile hashes). The hook's `--no-verify`
   was the right call for those commits, but it also dodged
   `ruff`/`pydocstyle`/`darglint`/`check-dead-utils` — so by the
   time the M8 upgrade ran pre-commit, 87 files needed
   auto-format and 40+ symbols needed allowlist entries. Net
   effect: this PR shipped a `chore(lint)` commit it shouldn't have
   needed. Recommend tightening the boilerplate's pre-commit story
   so the hook can pass `--generate-hashes` (or move the lock check
   to CI).
2. **`from_exception` patches `request_id` to `None` (not from any
   ContextVar).** Intentional — the kit doesn't know about our
   bridge — but it means our DRF handler has to `body["request_id"]
   = get_request_id()` after the call. Worth a note in the doc that
   adopters' handlers should top up the field from their own
   context; non-obvious otherwise.

## Suggested ROADMAP additions

Restated and prioritised for v0.1.x / v0.2 cycle planning:

| Priority | Item | Why |
|---|---|---|
| **P1** | Ship `DjangoSettingsSource` that reads `settings.RESILIENCE` | Closes the env-only config story; the dict is the natural Django knob |
| **P1** | Ship `resilience_kit.utils.*` (log_sanitization, network, timing, function_logger, data) | Five tiny modules every boilerplate re-implements |
| **P1** | Ship `GlobalThrottle` (port boilerplate's Lua impl) | In-process belt under nginx braces |
| **P2** | Free-function `resilience_kit.metrics.{record_duration, record_counter, record_gauge}` shim | Lets projects keep call sites + tee into pluggable backend |
| **P2** | `ResilienceKitError.details` as instance attribute, not `@property` | Removes the bridge-side shadow workaround |
| **P2** | Document the bridge + composition pattern in
  `MIGRATION-from-boilerplate-embedded.md` §2.5 | Next consumer
  shouldn't have to rediscover the bridge architecture |
| **P3** | DRF-shaped `verify_envelope_contract` example in Appendix B | Doc gap §3 above |
| **P3** | `BindRequestIdMiddleware` snippet in Appendix B | Doc gap §1 above |

Effort tags pulled from `docs/m7-kit-integration-report.md` §7
(KIT-M7-01..13); this report is the second data point feeding the
same ROADMAP planning round.
