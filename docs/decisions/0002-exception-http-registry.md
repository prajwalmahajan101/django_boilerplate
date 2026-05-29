# ADR-0002: Exception → HTTP status registry (lazy-frozen, double-checked)

- **Status:** Accepted
- **Date:** 2026-05-29
- **Deciders:** platform team

## Context

The custom DRF exception handler must map ~20 typed exception classes
across four families (`InfrastructureError`, `RepositoryError`, the auth
family, and per-domain subclasses) onto HTTP status codes. Three
constraints make a naïve hand-coded `isinstance` chain unsatisfactory:

1. **Domain apps register their own exceptions.** `accounts/`, and any
   future app added next to it, must be able to attach a status code
   for an exception they introduced without editing `core`.
2. **Registration happens at import time + `AppConfig.ready()` time.**
   Some mappings load before the first request, others register late
   under the app registry. The handler is then called concurrently
   across gthread worker threads.
3. **Specificity matters.** `S3NotFoundError` (a subclass of
   `S3Exception`) must be evaluated before its parent so the more
   specific status wins.

The `core/exceptions/handler.py` registry — `register_exception_mapping()`
plus a lazy-frozen tuple — is the chosen pattern. This ADR records the
contract so future contributors don't drift it.

## Decision

* **Mappings are stored in a list, frozen to a tuple on first read,
  and invalidated whenever a new entry is registered.** Append +
  invalidate happen under `_status_map_lock`; the tuple is rebuilt
  under the same lock by the first reader after invalidation
  (double-checked locking). Concurrent readers either see the prior
  frozen tuple in full or wait for the rebuild — never a half-built
  view.
* **Registration order = evaluation order.** Subclasses must be
  registered before their parents. `register_exception_mapping(S3Exception, 502)`
  must come before `register_exception_mapping(ExternalServiceError, 502)`
  even when both map to the same status, because future re-mapping of
  the parent (or insertion of a sibling-specific subclass) relies on
  the position invariant.
* **Per-instance `status_code` wins over registration.**
  `BaseCustomError(..., status_code=409)` and class-level
  `status_code = 4xx` attributes are honoured by the handler before it
  consults the registry. The new typed families (`APIError`,
  `AuthenticationFailedError`, `ValidationError`, `RateLimitError`)
  declare `status_code` as a class attribute and do **not** call
  `register_exception_mapping` — the class-attribute path is the
  canonical declaration for those, the registry remains the canonical
  declaration for the infrastructure / repository families that don't
  carry a status attr.
* **Each module that defines a new exception family registers its own
  mappings at the bottom of the file** (for non-`status_code`-bearing
  classes) or omits registration entirely (for `status_code`-bearing
  classes). `core/exceptions/handler.py` only registers the families
  defined alongside it; it never reaches into domain apps.

## Consequences

* Adding a new typed exception is a two-line change: define the class
  with `status_code = 4xx` (recommended) or call
  `register_exception_mapping()` (legacy path, still supported).
* No global frozen list to keep alphabetised — order is encoded in the
  call sites, which sit next to the class definitions, so a code-review
  diff that adds a subclass naturally shows the ordering requirement.
* Late registration during a hot request is safe because the cache is
  invalidated atomically and the next handler call rebuilds it. The
  cost is a single tuple allocation per re-registration, which never
  happens in a steady-state request path.
* The `hasattr(exc, "status_code")` short-circuit in the handler is
  load-bearing for the new typed families — removing it would silently
  fall through to the 500 default for `APIError` / `ValidationError` /
  `RateLimitError` / `AuthenticationFailedError` even though their
  class attribute is set. Don't.

## Alternatives considered

* **Hand-rolled `if isinstance(...) elif ...` chain.** Rejected:
  domain apps can't extend `core` without editing it.
* **Decorator on the exception class** (e.g. `@http_status(404)`).
  Rejected: identical semantic to a class attribute but requires an
  extra import + decorator at every definition site. The class
  attribute is one line shorter and grep-able.
* **Registry keyed on `error_code` string.** Rejected: defeats the
  subclass-specificity ordering — `isinstance` semantics are what make
  `S3NotFoundError` work without a separate code.
