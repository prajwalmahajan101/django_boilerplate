# Class Diagrams

Mermaid class diagrams for the base hierarchy and the resilience
layering. GitHub renders these natively.

## Base hierarchy

```mermaid
classDiagram
    class BaseModel {
        +bool is_active
        +datetime created_at
        +datetime updated_at
        +User created_by
        +User updated_by
        +save(skip_validation=False)
        +full_clean()
    }
    class NamedBaseModel {
        +str name
    }
    class BaseService~T~ {
        +type[T] model
        +frozenset allowed_filter_fields
        +int max_page_size
        +get_queryset() QuerySet
        +get(pk) T
        +list(filters, active_only=True) QuerySet
        +list_paginated(...)
        +create(data, user) T
        +update(pk, data, user) T
        +delete(pk, soft=True, user)
        +bulk_create(...)
        +bulk_update(...)
        +pre_create(data, user) data
        +post_create(instance, user)
        +pre_update(...)
        +post_update(...)
    }
    class BaseRepository~M~ {
        +type[M] model
        +get_by_id(pk) M
        +get_active_by_id(pk) M
        +list(active_only=True) QuerySet
        +list_paginated(...)
        +filter(...) QuerySet
        +exists(...) bool
        +count(...) int
        +add(instance, user=None) M
        +add_all(instances, user=None) list
        +update(pk, data, user=None) M
        +delete_hard(instance)
        +delete_hard_by_id(pk)
    }
    class BaseSchema {
        +bool drop_empty_on_output
        +to_representation(instance)
    }
    class BaseModelSchema {
        +bool drop_empty_on_output
        +to_representation(instance)
    }
    class BaseCustomError {
        +str default_message
        +str error_code
        +int status_code
        +str request_id
        +get_error_code() str
        +get_details() dict
        +to_error_dict() dict
    }

    NamedBaseModel --|> BaseModel
    BaseRepository~M~ ..> BaseModel : operates on
    BaseService~T~ ..> BaseModel : operates on
    BaseModelSchema --|> BaseSchema
    InfrastructureError --|> BaseCustomError
    DecryptionError --|> InfrastructureError
    FernetUnavailableError --|> InfrastructureError
    EncryptionConfigError --|> InfrastructureError
    ExternalServiceError --|> InfrastructureError
    ServiceUnavailableError --|> InfrastructureError
```

## Resilience layering

```mermaid
classDiagram
    class resilient_decorator["@resilient(service_name)"] {
        +wraps callable
        +retry on TransientError
        +circuit breaker per service
    }
    class ResilienceRegistry {
        +dict _breakers
        +RLock _lock
        +register_service(name, config)
        +get_breaker(name) BaseCircuitBreaker
    }
    class BaseCircuitBreaker {
        +str name
        +float time_until_retry
        +is_available() bool
        +record_success()
        +record_failure(exc)
        +reset()
        +get_stats() dict
    }
    class PyBreakerCircuitBreaker {
        +pybreaker.CircuitBreaker _breaker
        +float _opened_at
    }
    class ValkeyCircuitBreaker {
        +ValkeyClient client
        +str key_prefix
    }
    class BaseCache {
        +get(key) Any
        +set(key, value, ttl)
        +delete(key)
    }
    class InMemoryCache
    class ValkeyCache
    class BaseThrottle {
        +allow_request(request, view) bool
        +wait() float
    }
    class UserTierThrottle
    class BurstThrottle
    class GlobalThrottle {
        +Lua script (atomic fixed window)
    }
    class GlobalLuaCache {
        +str _sha
        +Lock _lock
        +get_sha() str
        +reset()
        +ensure_loaded(factory) str
    }

    resilient_decorator --> ResilienceRegistry
    ResilienceRegistry --> BaseCircuitBreaker
    PyBreakerCircuitBreaker --|> BaseCircuitBreaker
    ValkeyCircuitBreaker --|> BaseCircuitBreaker
    InMemoryCache --|> BaseCache
    ValkeyCache --|> BaseCache
    UserTierThrottle --|> BaseThrottle
    BurstThrottle --|> BaseThrottle
    GlobalThrottle --|> BaseThrottle
    GlobalThrottle --> GlobalLuaCache : SCRIPT LOAD once
```

## Auth provider chain

```mermaid
classDiagram
    class AuthProvider {
        <<Protocol>>
        +str name
        +authenticate(request) tuple|None
    }
    class APIKeyProvider {
        +str name = "api_key"
        +APIKeyAuthentication _auth
    }
    class JWTProvider {
        +str name = "jwt"
        +JWTAuthentication _auth
    }
    class GoogleOAuthProvider {
        +str name = "oauth_google"
    }
    class CompositeAuthentication {
        +authenticate(request) tuple|None
        +authenticate_header(request) str|None
    }
    class registry["core.auth.registry"] {
        +dict _REGISTRY
        +set _WARNED_UNKNOWN
        +register(provider)
        +unregister(name)
        +registered_names() list
        +enabled_providers() list
    }

    APIKeyProvider ..|> AuthProvider
    JWTProvider ..|> AuthProvider
    GoogleOAuthProvider ..|> AuthProvider
    CompositeAuthentication --> registry : enabled_providers()
    registry --> AuthProvider : holds
```

## Related reading

- [data-model.md](data-model.md) — `BaseModel` / `BaseService` contract.
- [resilience.md](resilience.md) — `@resilient` decorator behaviour.
- [authentication.md](authentication.md) — provider chain at request time.
- [exceptions.md](exceptions.md) — full `BaseCustomError` hierarchy.
