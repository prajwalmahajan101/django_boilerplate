# ADR-0004: Outsource the resilience stack to `resilience-kit`

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** Prajwal Mahajan

## Context

Pre-M7 the boilerplate carried ~3,550 source lines of in-tree
resilience code: circuit breakers (Valkey-backed + PyBreaker
fallback), retry / backoff, throttles (Lua + DRF wrappers), the
`http_client` with SSRF guard, Fernet-backed `EncryptedCharField`,
the recovery monitor, and an audit-event drain. The exact same
modules — line-for-line in many places — lived in
`fastapi_boilerplate`. Every release diverged a little; reconciling
the two repos was a tax on every change to a resilience seam.

A standalone package, `resilience-kit`, was extracted from the
shared subset to give both projects one source of truth, semver'd
upgrades, and a coherent story for downstream forks. By the time
M7+M8 (PR #8) landed, the kit had reached `0.1.0` with stable
public surface for breakers, retry, throttles, SSRF, crypto, audit
sink, and lifecycle.

The decision was whether to **adopt the kit as a hard dependency**
(deleting the in-tree code) or **keep parity copies** (continuing
to drift). Adoption closed the gap; deferral kept ~30 call sites
locked to in-tree behaviour that nobody had time to maintain.

## Decision

We will depend on `resilience-kit==0.1.0` and delete the in-tree
resilience implementation. The boilerplate retains only the
**bridges** needed to compose the kit with Django-specific
infrastructure:

- `apps/core/middleware/bind_request_id.py` — bridges the kit's
  `request_id` into `core.context` so existing structured-logging
  filters keep working.
- Exception handler composition — kit's `ResilienceKitError`
  family is registered alongside `BaseCustomError` via
  `register_exception_mapping()` so DRF's handler maps both into
  the standard envelope.
- `apps/core/apps.py::CoreConfig._register_resilience_services()`
  — boilerplate-side registration of each outbound service
  (`partner_api`, `s3`, …) into the kit's per-service registry.
- `apps/core/base/fields.py` — re-exports
  `EncryptedCharField` from `resilience_kit.adapters.django.fields`
  so existing model imports (`from core.base.fields import
  EncryptedCharField`) keep resolving without a migration.
- `core.registries` — re-exports `register_resilience_service`,
  `resilience_registry` from the kit so domain apps' `AppConfig`
  files don't need a kit import path.

The `@resilient("service_name")` decorator and the throttle
classes (`BurstThrottle`, `AuthEndpointThrottle`) are imported
directly from `resilience_kit` at every call site — no boilerplate
shim. Kit lifecycle (recovery monitor, audit drain, atexit cleanup,
autoreload guard) runs from the kit's own `ResilienceConfig.ready()`.

## Consequences

### Positive

- **Single source of truth.** A bug fix or hardening in the kit
  reaches `django_boilerplate` and `fastapi_boilerplate` on the
  same release.
- **Source-line debt cleared.** -3,550 lines of resilience source
  and -746 lines of resilience tests removed from this repo (PR
  #8). The deleted code includes the Valkey-Lua throttle scripts,
  the PyBreaker fallback wiring, the recovery-monitor loop, and
  the audit-sink batching.
- **Lifecycle automation.** Recovery monitor, audit drain, atexit
  cleanup, and the dev-autoreload guard are kit-owned. Nothing on
  the boilerplate side has to start, stop, or reset them.
- **Upgrade story.** `resilience-kit` is semver'd; future security
  / capability work lands as a version bump rather than a manual
  port across two repos.

### Negative

- **Cold-start latency.** Importing `resilience_kit` at AppConfig
  time pulls `pydantic`, `pydantic-settings`, `httpx`, `tenacity`,
  and `pybreaker`. Measured +100–200ms cold start on a
  development laptop. Acceptable for a web boilerplate; documented
  here so a downstream profiling pass knows where to look.
- **Legacy env-var names silently dropped.** Pre-M7 settings
  consumed `RATE_LIMIT_*` and the in-tree `FIELD_ENCRYPTION_KEY`
  semantics directly. The kit reads `RESILIENCE_*` /
  `RESILIENCE_DEFAULTS__*` prefixed names. M8 added
  `resilience_kit.adapters.django.legacy_env_alias()` so a
  downstream fork can wire one-shot translations from old names
  to new — but the boilerplate ships no translations by default.
  See `docs/configuration.md` for the env-var prefix.
- **`GlobalThrottle` dropped.** The pre-M7 process-wide 10k/min
  Lua throttle (sat above DRF's per-scope throttles as a
  defense-in-depth cap) is not in the kit. nginx-layer rate
  limiting is the documented fallback; a project that needs
  in-process global throttling has to add it back.
- **Visible-surface coupling.** The boilerplate's behaviour is now
  partly defined in a versioned external package. A kit upgrade
  can change observable behaviour (throttle keys, breaker state
  format) without a boilerplate commit. Mitigation: the
  `requirements/base.in` pin is exact (`==0.1.0`); upgrades go
  through the same PR review path as any other dependency change.

### Neutral

- **`RESILIENCE` settings dict is mostly cosmetic.** The kit reads
  `RESILIENCE["services"]` to seed per-service registry entries;
  the rest of the dict is decorative. Env-prefixed overrides
  (`RESILIENCE_*`) always win.
- **No Django migration churn.** `EncryptedCharField` is a kit
  re-export, ciphertext shape unchanged; existing rows decrypt
  without intervention. `_state` / `_meta` of the model class is
  identical from Django's perspective.
- **Import paths stable.** `from core.registries import …`,
  `from core.base.fields import EncryptedCharField`, and
  `from resilience_kit.adapters.django.drf_throttles import
  BurstThrottle` all work — the only churn was the deletion of
  `apps/core/resilience/`, which had no remaining callers post-
  migration.

## Alternatives considered

- **Keep the in-tree implementation.** Drift between this repo
  and `fastapi_boilerplate` continues; every release has to
  resolve the same conflict surface. Rejected: the migration cost
  amortises within two release cycles.
- **Vendor the kit's source into `apps/core/_kit/`.** Locks the
  version, keeps upgrades manual. Rejected: defeats the point of
  publishing the kit; the upgrade path is exactly what we want.
- **Split into per-concern micro-libraries** (one for breakers,
  one for throttles, one for crypto). Rejected: four upgrade
  matrices instead of one; the kit's cross-concern lifecycle
  (single recovery monitor, single audit drain) wouldn't survive
  the split.
- **Adopt only the breakers, keep everything else in-tree.**
  Rejected: the throttles + crypto were exactly the shared
  surface where the two repos drifted hardest; breakers alone
  wouldn't have justified the package extraction.

## References

- PR #8 — M7 Phase 3 migration commit (11 atomic commits, 48
  merge conflicts resolved, 180 tests passing post-migration).
- [docs/m7-kit-integration-notes.md](../m7-kit-integration-notes.md)
- [docs/m7-outcome-report.md](../m7-outcome-report.md)
- [docs/m8b-upgrade-report.md](../m8b-upgrade-report.md)
- [docs/resilience.md](../resilience.md) — usage guide.
- [ADR-0003](0003-ci-as-quality-gate.md) — adjacent decision:
  CI is the gate that catches kit-upgrade regressions.
