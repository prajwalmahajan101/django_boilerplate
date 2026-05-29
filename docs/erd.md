# Entity-Relationship Diagram

Mermaid-rendered ERD for the shipped models. GitHub renders this
natively; no external tool required.

```mermaid
erDiagram
    USER ||--o{ APIKEY : owns
    USER }o--o{ ROLE : "M2M (User.roles)"
    ROLE }o--o{ PERMISSION : "M2M (Role.permissions)"

    USER {
        bigint id PK
        string email UK "USERNAME_FIELD"
        string username
        string avatar_url
        bool email_verified
        string timezone
        ip last_login_ip
        bool is_staff "Django admin access"
        bool is_active
        datetime date_joined
        datetime last_login
    }

    ROLE {
        bigint id PK
        string name UK
        text description
        bool is_superuser_role "bypasses RBAC checks"
        bool is_default "auto-assigned on OAuth signup"
        bool is_active
        datetime created_at
        datetime updated_at
    }

    PERMISSION {
        bigint id PK
        string resource "core.enums.Resource"
        string action "core.enums.Action"
        bool is_active
    }

    APIKEY {
        uuid id PK
        bigint user_id FK
        string name "human-readable label"
        string prefix "8-char indexed lookup"
        string secret "Fernet-encrypted at rest"
        datetime last_used_at
        datetime revoked_at "null = active"
        bool is_active
        datetime created_at
        datetime updated_at
    }

    APILOG {
        uuid id PK
        string direction "INBOUND | OUTBOUND"
        string service_name
        string request_id
        string method
        text url
        int status_code
        float duration_ms
        json request_headers
        text request_body
        json response_headers
        text response_body
        json error
        json extra
        datetime created_at
        int ttl_expires_at "epoch seconds"
    }
```

## Constraints worth noting

- `Permission(resource, action)` is unique — see
  `apps/accounts/models.py:29-44` for the `UniqueConstraint` +
  `CheckConstraint` pair.
- `APIKey.prefix` has a **partial index** scoped to
  `is_active=True AND revoked_at IS NULL` — see
  `apps/accounts/models.py:172-176`. The hot lookup path
  (`prefix=..., is_active=True, revoked_at__isnull=True`) is
  index-only.
- `APILog` has composite indexes on `(service_name, created_at)` and
  `(direction, created_at)` for the audit dashboard.
- `User.email` is `USERNAME_FIELD`; do not change after first
  migration — see `apps/accounts/CLAUDE.md`.

## Soft-delete

Models inheriting from `BaseModel` (`APIKey`) carry an `is_active`
flag and route writes through `BaseService.delete(soft=True, user)`
which cascades soft-deletes via
`BaseService._cascade_soft_delete_bfs`.
`User`, `Role`, `Permission` carry `is_active` too but use Django
auth's own semantics for `User.is_active`.

## Related reading

- [data-model.md](data-model.md) — `BaseModel` / `BaseService` contract.
- [authentication.md](authentication.md) — how `APIKey` and JWT flow
  through the auth provider registry.
- [audit-trail.md](audit-trail.md) — `APILog` write pipeline.
