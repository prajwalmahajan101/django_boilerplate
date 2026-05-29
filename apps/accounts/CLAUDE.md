# accounts — Authentication & authorization

> **Auth design:** [../../docs/authentication.md](../../docs/authentication.md) · **Sequence diagrams:** [../../docs/sequence-diagrams.md](../../docs/sequence-diagrams.md) (OAuth login, API-key auth, JWT+RBAC) · **Audit trail:** [../../docs/audit-trail.md](../../docs/audit-trail.md)

Handles all auth (Google OAuth2, JWT, API keys) and RBAC (roles → permissions with `(Resource, Action)` pairs).

## Models

- **`User`** — extends `AbstractUser`; `email` is `USERNAME_FIELD`; `roles` M2M is the RBAC relation; `has_superuser_role` is a `cached_property` that short-circuits permission checks.
- **`Role`** — `is_superuser_role` bypasses `HasResourcePermission`; `is_default` is auto-assigned to new OAuth users.
- **`Permission`** — `(resource, action)` pairs are globally unique. Enums in `core/enums.py`; adding a new resource is an enum edit, no migration.
- **`APIKey`** — `prefix` (first 8 chars) for fast lookup; full key `EncryptedCharField` compared with `hmac.compare_digest`. `create_key(user, name)` returns `(instance, raw_key)` — raw shown once only.

## Conventions

- **Every view sets `resource` + `action`** class attrs. `HasResourcePermission` handles the lookup; don't hand-roll permission checks.
- **Per-request permission cache is automatic** — `HasResourcePermission` stores results on the request object keyed by `(resource, action)`. Checking the same pair twice costs one DB query.
- **Never change `USERNAME_FIELD` or `REQUIRED_FIELDS`** after first migration. Django auth machinery depends on them.
- **`UserService.update_profile` validates timezone** against `zoneinfo.available_timezones()` and `select_for_update`s the row. Only `first_name` / `last_name` / `timezone` are writable; `email` and `roles` are not.
- **`RBACBackend`** maps Django's string permission format (`"app.action_model"`) to `(Resource, Action)` tuples — required for admin-panel integration.

## Gotchas

- `is_staff=True` controls Django admin access and is **separate** from `is_superuser_role`. Users can have one without the other.
- `POST /api/accounts/logout/` validates the refresh token belongs to the authenticated user before blacklisting it. Don't skip this check — it's a security boundary, not a convenience.
- `allauth` adapter in `adapters.py` and the `SOCIALACCOUNT_ADAPTER` setting in `base.py` must stay in sync.
- Adding a new `Permission` row for an existing `(resource, action)` pair is a no-op — the unique constraint prevents duplicates. To revoke, remove from Role.permissions M2M, not delete the Permission row.
