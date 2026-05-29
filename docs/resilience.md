# Resilience Patterns

## Overview

The Co-Lending Gateway implements defense-in-depth resilience across three layers:

1. **Nginx** — Rate limiting at the reverse proxy (first line of defense)
2. **DRF Throttles** — Application-level rate limiting per user tier
3. **Service-Level** — Circuit breaker, retry, and caching for external service calls

All resilience components are designed to **fail-open**: if the resilience infrastructure itself fails (e.g., Valkey goes down), requests are allowed through rather than blocking all traffic.

---

## Circuit Breaker

### States

```mermaid
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> OPEN : failure_count >= fail_max (default 5)
    OPEN --> HALF_OPEN : recovery_timeout elapsed (default 30s)
    HALF_OPEN --> CLOSED : success_count >= success_threshold (default 2)
    HALF_OPEN --> OPEN : any failure
    OPEN --> OPEN : request arrives → ServiceUnavailableError (503)
```

| State | Behaviour |
|-------|-----------|
| CLOSED | Normal — all requests pass through |
| OPEN | Short-circuit — immediately raises `ServiceUnavailableError` (503) |
| HALF_OPEN | Trial — limited requests probe recovery |

### Backend Selection (Provider Pattern)

```mermaid
flowchart TD
    A([get_registry called]) --> B{Singleton\nalready created?}
    B -- yes --> C([Return cached registry])
    B -- no --> D[Try ValkeyRegistry\nconnect + SCRIPT LOAD Lua]
    D --> E{Valkey\navailable?}
    E -- yes --> F([ValkeyRegistry\ndistributed, shared across workers])
    E -- no --> G([PyBreakerRegistry\nper-process, in-memory fallback])
```

**Valkey backend** (preferred):
- State stored as Valkey hash `cb:{service_name}`
- Fields: `state`, `failure_count`, `success_count`, `last_failure`
- TTL: `recovery_timeout × 10` (refreshed on every write)
- All state transitions via a single atomic Lua `EVALSHA` — no race conditions across Gunicorn workers

**PyBreaker backend** (fallback):
- In-memory state, isolated per worker process
- Workers can have diverging views of circuit state
- Used transparently when Valkey is unavailable

### Per-Request Flow

```mermaid
flowchart TD
    A([Decorated function called]) --> B[breaker.call func]
    B --> C{is_available?\nEVALSHA or pybreaker}
    C -- OPEN → false --> D([Raise ServiceUnavailableError 503])
    C -- CLOSED/HALF_OPEN → true --> E[Call wrapped function]
    E --> F{Exception\nraised?}
    F -- no --> G[record_success\nEVALSHA or pybreaker]
    G --> H{State was\nHALF_OPEN?}
    H -- yes --> I{success_count\n>= threshold?}
    I -- yes --> J[Transition → CLOSED\nreset failure_count]
    I -- no --> K([Return result])
    H -- no --> K
    J --> K
    F -- yes --> L{Exception in\nexcluded_exceptions?}
    L -- yes --> M([Propagate without\nrecording failure])
    L -- no --> N[record_failure\nEVALSHA or pybreaker]
    N --> O{failure_count\n>= fail_max\nor was HALF_OPEN?}
    O -- yes --> P[Transition → OPEN\nset last_failure=now]
    O -- no --> Q([Propagate exception])
    P --> Q
```

### Valkey Lua Script (Atomicity)

All state reads and writes happen in a **single EVALSHA round-trip** using the `CIRCUIT_BREAKER_LUA_SCRIPT`. The script:
1. Reads the current hash state
2. Checks if an OPEN circuit has timed out (auto-transitions to HALF_OPEN)
3. Applies the requested action (`is_available`, `record_success`, `record_failure`, `reset`)
4. Writes back the new state with a refreshed TTL

This makes all state transitions atomic — no multi-step read/modify/write race between concurrent workers.

### Valkey Fallback (per-breaker)

```mermaid
flowchart LR
    A([_call_lua action]) --> B{EVALSHA\nsucceeds?}
    B -- yes --> C([Return result\n_using_fallback=False])
    B -- NoScriptError --> D[Reload script\nscript_load + retry]
    D --> C
    B -- ConnectionError\nor other --> E[Log warning once\n_using_fallback=True]
    E --> F([Delegate to\nPyBreakerCircuitBreaker])
```

### Configuration

```python
RESILIENCE_DEFAULTS = {
    "circuit_breaker": {
        "fail_max": 5,              # Failures before OPEN
        "reset_timeout": 30,        # Seconds in OPEN before HALF_OPEN
        "success_threshold": 2,     # Successes in HALF_OPEN to close
        "excluded_exceptions": [],  # Never counted as failures
    }
}
```

Per-service overrides via the registry:

```python
from core.resilience.registry import registry

registry.register_service("partner_api", {
    "circuit_breaker": {"fail_max": 3, "reset_timeout": 60},
})
```

### Usage

```python
from core.resilience.decorators import circuit_breaker

@circuit_breaker("partner_api")
def call_partner(url, data):
    return make_http_request("POST", url, json_body=data)
```

---

## Retry

### Flow

```mermaid
flowchart TD
    A([retry_on_failure decorator\ncalled]) --> B{Decorator cached\nfor service?}
    B -- yes --> C[Use cached Tenacity decorator]
    B -- no --> D[Load config from registry\nmax_attempts, wait_min/max, retry_on]
    D --> E[Exclude ServiceUnavailableError\nfrom retry_on list]
    E --> F[Build Tenacity retry decorator\nstop=max_attempts\nwait=exponential min/max\nreraise=True]
    F --> G[Cache decorator for service]
    C --> H
    G --> H[Attempt 1: call function]
    H --> I{Exception?}
    I -- no --> Done([Return result])
    I -- yes: in retry_on --> J{Attempts\nexhausted?}
    J -- no --> K[Wait exponential backoff\n1s → 2s → 4s capped at 10s]
    K --> L[Attempt N]
    L --> I
    J -- yes --> M([Re-raise last exception])
    I -- yes: not in retry_on --> N([Propagate immediately\nno retry])
```

### Exception Hierarchy for Retry

```
BaseCustomError
└── InfrastructureError
    ├── TransientError          ← retried by default
    ├── ExternalTimeoutError    ← retried by default
    ├── ServiceUnavailableError ← NEVER retried (open circuit guard)
    ├── ExternalServiceError    ← not retried by default
    ├── S3Exception             ← not retried by default
    └── PartnerPushError        ← not retried by default
```

**Why `ServiceUnavailableError` is excluded**: when used inside `@resilient`, the circuit breaker wraps the retried function. If a retry attempt opens the circuit, subsequent retry attempts would hit the open circuit and raise `ServiceUnavailableError`. Excluding it prevents retry from defeating the circuit breaker.

See [exceptions.md](exceptions.md) for the full typed exception hierarchy and how `excluded_exceptions` interacts with the DRF handler.

### Configuration

```python
RESILIENCE_DEFAULTS = {
    "retry": {
        "max_attempts": 3,
        "wait_min": 1,   # seconds
        "wait_max": 10,  # seconds
        "retry_on": [
            "core.exceptions.infrastructure.TransientError",
            "core.exceptions.infrastructure.ExternalTimeoutError",
        ],
    }
}
```

### Usage

```python
from core.resilience.retry import retry_on_failure

@retry_on_failure("synoriq_db")
def fetch_lead_data(app_number):
    return execute_query(engine, sql, {"app_number": app_number})
```

---

## Combined: `@resilient`

`@resilient("service_name")` = circuit breaker (outer) wrapping retry (inner). The composition matters: the circuit breaker sees the final outcome after all retries, not each individual attempt.

```mermaid
sequenceDiagram
    participant Caller
    participant CB as Circuit Breaker
    participant Retry as Retry (Tenacity)
    participant Fn as External Function

    Caller->>CB: call(fn, *args)
    CB->>CB: is_available()?
    alt OPEN
        CB-->>Caller: raise ServiceUnavailableError
    else CLOSED or HALF_OPEN
        CB->>Retry: retried_fn(*args)
        loop Up to max_attempts
            Retry->>Fn: attempt N
            alt Transient failure
                Fn-->>Retry: raise TransientError
                Retry->>Retry: wait exponential backoff
            else Success
                Fn-->>Retry: return result
                Retry-->>CB: return result
            end
        end
        alt All attempts exhausted
            Retry-->>CB: raise TransientError (last)
        end
        alt Success
            CB->>CB: record_success()
            CB-->>Caller: return result
        else Failure
            CB->>CB: record_failure()
            CB-->>Caller: raise exception
        end
    end
```

```python
from core.resilience.decorators import resilient

@resilient("s3")
def upload_document(data, bucket, key):
    return upload_json_to_s3(data, bucket, key)
```

---

## Resilience Registry

```mermaid
flowchart TD
    A([get_config service_name]) --> B[Copy RESILIENCE_DEFAULTS]
    B --> C{Per-service overrides\nregistered?}
    C -- yes --> D[Merge overrides into\ncircuit_breaker and retry sections]
    C -- no --> E
    D --> E[Resolve dotted-path strings\nin retry_on to exception classes]
    E --> F([Return merged config dict])

    G([get_breaker service_name]) --> H{Breaker already\ncreated?}
    H -- yes --> I([Return cached breaker])
    H -- no --> J[Lock _lock\ndouble-check]
    J --> K[get_config service_name]
    K --> L[get_registry\ncreate ValkeyCircuitBreaker\nor PyBreakerCircuitBreaker]
    L --> M[Cache in _breakers dict]
    M --> I
```

**Registration rules**:
- Call `registry.register_service()` before the first request that triggers `get_breaker()` (typically in `AppConfig.ready()`).
- Registering after a breaker has been created raises `ValueError` — configuration cannot change once the breaker is live.

---

## Rate Limiting (Throttling)

### Three-Layer Defense

```mermaid
flowchart TD
    Client([Incoming request]) --> Nginx

    subgraph Nginx ["Layer 1 — Nginx (reverse proxy)"]
        N1{Zone: api\n30 req/s burst 50}
        N2{Zone: auth\n5 req/s burst 10}
        N3{Zone: admin\n10 req/s burst 20}
    end

    Nginx --> N1
    N1 -- allowed --> DRF
    N1 -- exceeded --> R1([429 Too Many Requests\nno upstream hit])

    subgraph DRF ["Layer 2 — DRF Throttles (app level)"]
        T1[BurstThrottle\n10 req/s per identity]
        T2[UserTierThrottle\nanon 100/h · user 1000/h · admin 5000/h]
        T3[GlobalThrottle\n10 000 req/min cluster-wide]
    end

    DRF --> T1 --> T2 --> T3

    T3 -- all passed --> View([View handler])
    T1 -- exceeded --> R2([429 + X-RateLimit headers])
    T2 -- exceeded --> R2
    T3 -- exceeded --> R2

    View --> SVC

    subgraph SVC ["Layer 3 — Service resilience"]
        CB[Circuit Breaker\nper external service]
    end

    CB -- OPEN --> R3([503 ServiceUnavailable])
    CB -- CLOSED → call + retry --> Ext([External API / DB])
```

### Throttle Provider Selection

```mermaid
flowchart TD
    A([get_throttle_classes\nsingleton]) --> B{Already\nresolved?}
    B -- yes --> C([Return cached dict])
    B -- no --> D[Ping Valkey rate_limit alias]
    D --> E{Valkey\nresponds?}
    E -- yes --> F([Return Valkey-backed classes\nUserTierThrottle, BurstThrottle,\nGlobalThrottle, EndpointThrottle])
    E -- no --> G([Return DRF fallback classes\nDRFUserTierThrottle, DRFBurstThrottle,\nDRFGlobalThrottle, DRFEndpointThrottle])
```

Both sets of classes implement the same `allow_request` interface — DRF and the rest of the app are unaware of which backend is active.

### Per-Request Throttle Flow (Valkey path)

```mermaid
flowchart TD
    A([allow_request called]) --> B{rate is None?}
    B -- yes --> Pass([return True — no limit])
    B -- no --> C[Build cache key:\nthrottle_{scope}_{user_pk or IP}]
    C --> D{Lua script\nloaded?}

    D -- yes\natomic path --> E[EVALSHA THROTTLE_LUA_SCRIPT\nZREMRANGEBYSCORE expire\nZCARD count\nif count < limit: ZADD]
    E --> F{allowed?}
    F -- yes --> G[Set request._throttle_limit\n._throttle_remaining\n._throttle_reset]
    G --> Pass2([return True])
    F -- no --> H[Log throttle_event\nSet remaining=0]
    H --> Fail([return False → 429])

    D -- no\nnon-atomic fallback --> I[CACHE GET key → history list\nDrop entries outside window\nCount remaining]
    I --> J{len history\n>= limit?}
    J -- yes --> H
    J -- no --> K[Insert now into history\nCACHE SET key history duration]
    K --> Pass2
```

### Global Throttle — Sliding Window Counter

The `GlobalThrottle` uses a different algorithm (O(1) vs the O(log n) sorted-set approach used by other throttles) to handle cluster-wide counting cheaply.

```mermaid
flowchart LR
    A([Request at time T]) --> B[window_start = floor T/window × window\nwindow_pos = T-start / window]
    B --> C[current_key = prefix:window_start\nprev_key = prefix:window_start-window]
    C --> D[GET current_count\nGET prev_count]
    D --> E[effective = current + prev × 1-window_pos\nlinear interpolation]
    E --> F{effective\n>= limit?}
    F -- yes --> G([429 — return False])
    F -- no --> H[INCR current_key\nEXPIRE current_key = window×2]
    H --> I([Allowed — return True])
```

The interpolation smooths bursty traffic at window boundaries without the full history scan that a pure sliding window needs.

### User Tier Resolution

```mermaid
flowchart LR
    A([get_user_tier request]) --> B{request.user\nauthenticated?}
    B -- no --> Anon([tier = anon\n100 req/h])
    B -- yes --> C{user.has_superuser_role?}
    C -- yes --> Admin([tier = admin\n5000 req/h])
    C -- no --> User([tier = user\n1000 req/h])
```

`has_superuser_role` is resolved via `RBACBackend` — users with the superuser Role get admin-tier rate limits automatically.

### Rate Limit Response Headers

`RateLimitHeadersMiddleware` (last in middleware stack) reads attributes set by the throttle on `request` and injects them into the response:

```
X-RateLimit-Limit: 1000        # requests allowed in window
X-RateLimit-Remaining: 997     # requests left before throttle
X-RateLimit-Reset: 1713700000  # unix timestamp of window reset
```

Headers are set only when `RATE_LIMIT_CONFIG["ENABLE_HEADERS"]` is `True` (default). When a request is throttled, `Remaining` is set to `0` and `Retry-After` is returned by DRF.

### Fail-Open Behaviour

| Component | Fail-Open? | What happens on backend failure |
|-----------|------------|--------------------------------|
| Valkey throttle (atomic) | Yes | Exception caught, `fail_open` returned |
| DRF throttle fallback | Yes | Exception caught, `fail_open` returned |
| Global throttle Lua | Yes | Reloads script once, falls back to non-atomic |
| Circuit breaker (Valkey) | Yes | Falls back to per-process PyBreaker |
| Cache provider | Yes | Falls back to in-memory `LocMemCache` |

### Configuration

```bash
# Rate limits (all overridable via env vars)
RATE_LIMIT_ANON=100/hour
RATE_LIMIT_USER=1000/hour
RATE_LIMIT_ADMIN=5000/hour
RATE_LIMIT_BURST=10/second
RATE_LIMIT_GLOBAL=10000/minute
RATE_LIMIT_FAIL_OPEN=true
RATE_LIMIT_ENABLE_HEADERS=true

# Circuit breaker
RESILIENCE_CB_FAIL_MAX=5
RESILIENCE_CB_RESET_TIMEOUT=30

# Retry
RESILIENCE_RETRY_MAX_ATTEMPTS=3
RESILIENCE_RETRY_WAIT_MIN=1
RESILIENCE_RETRY_WAIT_MAX=10
```

## Caching

### Dual-Cache Architecture

| Alias | Valkey DB | Purpose | Fallback |
|---|---|---|---|
| `default` | DB 2 (local) | Application cache (bearer tokens, query results) | In-memory LocMemCache |
| `rate_limit` | DB 3 (local) | Rate limiting, circuit breaker state | In-memory LocMemCache |

Separation ensures rate limiting operations cannot evict application cache entries.

### Cache Provider

```python
from core.resilience.cache.provider import get_cache

cache = get_cache("default")  # or "rate_limit"
cache.set("key", "value", timeout=300)
value = cache.get("key")
```

The provider is a lazy singleton per alias. It tries Valkey first, falls back to in-memory.

### Fail-Open Behavior

The `ValkeyCacheBackend` wraps Django's cache framework with fail-open semantics:
- If Valkey is unavailable, operations silently fall back to `InMemoryCacheBackend`
- Tracks `_using_fallback` flag to avoid log spam
- `is_healthy()` method reports backend status

### Dual-cache read / write flow

```mermaid
flowchart TD
    Caller["Caller<br/>cache = get_cache(alias)<br/>alias ∈ {default, rate_limit}"] --> Provider{provider<br/>cached for alias?}
    Provider -- yes --> Backend[Return cached backend]
    Provider -- no --> Try[Try ValkeyCacheBackend<br/>PING Valkey on alias DB]
    Try --> Ping{Valkey<br/>reachable?}
    Ping -- yes --> PickValkey[Backend = ValkeyCacheBackend<br/>alias → DB 2 or DB 3]
    Ping -- no --> PickMem["Backend = InMemoryCacheBackend<br/>(Django LocMemCache scoped to alias)"]
    PickValkey --> Cache
    PickMem --> Cache
    Backend --> Cache[cache.get / cache.set / cache.delete]
    Cache --> Op{operation<br/>outcome}
    Op -- hit / success --> ReturnOK([return value / ok])
    Op -- miss --> ReturnMiss([return None / default])
    Op -- Valkey error mid-op --> FailOpen["Log WARNING once per backend<br/>(_using_fallback=True)<br/>retry on in-memory"]
    FailOpen --> ReturnMiss
```

Key properties of this design:
- **Alias isolation.** `default` and `rate_limit` are separate Valkey DBs (2 and 3 locally) — eviction under memory pressure on one cannot evict keys on the other.
- **Fail-open, not fail-closed.** When Valkey is down, callers see cache misses + warn logs, not exceptions. The app continues serving traffic without cache. Callers must design for "cache can return None at any time" regardless.
- **Startup resilience.** If Valkey is unavailable at process start, the provider picks in-memory for the process lifetime. It does **not** auto-recover mid-process — restarting the process re-runs the PING. This is intentional (fail-consistent over fail-sometimes) but means a mid-traffic Valkey recovery does not silently switch back.

See also [thread-safety.md](thread-safety.md) — the provider singletons per alias use `threading.Lock` for first-init and are safe under gthread.

## HTTP Client

For external HTTP calls, use the built-in resilient HTTP client:

```python
from core.utils.http_client import make_http_request

response = make_http_request(
    method="POST",
    url="https://api.partner.com/push",
    headers={"X-Partner-ID": "123"},
    json_body={"lead_data": {...}},
    timeout=30,
    max_attempts=3
)
# response: HttpResponse(status_code, body, headers)
```

Features:
- Thread-local `requests.Session` for connection pooling
- Automatic retry with exponential backoff on 5xx and timeouts
- Raises `TransientError` (5xx) or `ExternalTimeoutError` (timeout)
- Per-`max_attempts` Tenacity state caching

## Monitoring

### Circuit Breaker Stats

```python
from core.resilience.circuit_breaker.provider import get_registry

# Get stats for all breakers
stats = get_registry().get_all_stats()
# {
#   "partner_api": {
#     "state": "closed",
#     "failure_count": 1,
#     "success_count": 42,
#     "time_until_retry": 0
#   }
# }
```

### Observability

- **Structured logs**: All resilience events logged as JSON with request_id context
- **Sentry**: Unhandled exceptions and circuit breaker opens reported to Sentry
- **Flower**: Celery task monitoring (retries, failures, queue depth)
- **Health/Readiness**: `/api/health/` and `/api/readiness/` for load balancer checks
