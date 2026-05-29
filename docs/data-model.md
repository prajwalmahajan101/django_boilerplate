# Data model & service layer

> Reference for `BaseModel`, `NamedBaseModel`, and `BaseService[T]`.
> The *checklist* form lives in
> [adding-a-new-app.md](adding-a-new-app.md); this page is the
> *reference* — what every contract guarantees, what subclasses must
> honour, and which file owns which invariant.

Companion pages:
[architecture.md](architecture.md) (layering),
[audit-trail.md](audit-trail.md) (soft-delete cascade),
[exceptions.md](exceptions.md) (typed error envelope).

---

## Class hierarchy

```
                     ┌────────────────────────┐
                     │   models.Model         │ (django)
                     └───────────▲────────────┘
                                 │
                     ┌───────────┴────────────┐
                     │   BaseModel            │  abstract
                     │  (audit + soft-delete) │
                     └───────────▲────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
        ┌───────────┴───────────┐  ┌──────────┴────────────┐
        │ NamedBaseModel        │  │  YourConcreteModel    │
        │ + name, unique code   │  │  class Meta(           │
        └───────────────────────┘  │     BaseModel.Meta):  │
                                   │     ...                │
                                   └───────────────────────┘

   Service tier (independent hierarchy):

        ┌───────────────────────────┐
        │  BaseService[T: Model]    │
        │  ── CRUD + hooks + locks  │
        │  ── list() with page cap  │
        │  ── soft-delete BFS       │
        │  ── filter / order allow-lists
        └───────────────▲───────────┘
                        │
                ┌───────┴───────┐
                │ YourService   │  model = YourConcreteModel
                └───────────────┘
```

Source files:

- `apps/core/base/model.py` — `BaseModel`, `NamedBaseModel`.
- `apps/core/base/service.py` — `BaseService[T]`.
- `apps/core/base/fields.py` — `EncryptedCharField`.

---

## `BaseModel` — abstract

Fields:

| field | purpose | notes |
|---|---|---|
| `id` | `BigAutoField` PK | every model gets a 64-bit PK regardless of expected volume |
| `created_at` / `updated_at` | `auto_now_add` / `auto_now` | both `db_index=True` |
| `created_by` / `updated_by` | FK to `AUTH_USER_MODEL` with `SET_NULL` | services stamp these in `pre_create` / `pre_update` |
| `is_active` | soft-delete flag, `db_index=True` | `BaseService.delete(soft=True)` flips this; `_cascade_soft_delete_bfs` propagates to FK children |
| `notes` | `JSONField`, optional | catch-all for ad-hoc audit metadata |

### Invariants

1. **`updated_at >= created_at`** — enforced by `Meta.CheckConstraint`
   on the abstract, propagated to every concrete descendant whose
   `Meta` inherits from `BaseModel.Meta`. The constraint name uses the
   `%(app_label)s_%(class)s_` placeholder so each table gets its own
   uniquely-named constraint.

2. **`full_clean()` runs on every `.save()`** unless `skip_validation=True`
   is passed. The service layer also validates on its write paths — the
   model is the second line of defence.

### `Meta` inheritance contract

Concrete descendants **must** inherit `BaseModel.Meta` to pick up the
`CheckConstraint`. Without this inheritance, only the application-path
auto-`updated_at` keeps the invariant honest; admin / shell / raw-SQL
paths can smuggle in violations.

```python
class MyModel(BaseModel):
    ...
    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [...]
```

---

## `NamedBaseModel` — abstract

Extends `BaseModel` with:

- `name: CharField(max_length=255)`
- `code: CharField(max_length=100, unique=True)`

Use for top-level reference / domain entities that need a
human-readable label and a stable opaque identifier (e.g. `Role`).

---

## `BaseService[T]`

Generic over the model type so type-checkers can infer return types of
`create / update / list / get_by_id` without per-service annotations.

### Read API

| method | semantics |
|---|---|
| `get_by_id(pk)` | `None` on missing |
| `get_by_id_or_fail(pk)` | raises `EntityNotFoundError` |
| `get_active_by_id(pk)` | filters `is_active=True` |
| `list(filters, order_by, limit, offset, ...)` | with allow-list + page-cap |
| `filter(**kwargs)` / `exists(**kwargs)` / `count(...)` | allow-list checked |

### Write API

Every write runs inside `@transaction.atomic`. Hooks
(`pre_create` / `post_create` / `pre_update` / ...) are the
subclass extension points; do not override the public method.

| method | guarantees |
|---|---|
| `create(data, user)` | `full_clean()` via `BaseModel.save()` |
| `update(pk, data, user)` | row-level lock via repository, `full_clean()` via `.save()` |
| `bulk_create(list_)` | **explicit** `full_clean()` loop because Django bypasses `.save()` |
| `bulk_update(list_, fields)` | **explicit** `full_clean()` loop per instance before `QuerySet.bulk_update()` (also bypasses `.save()`); `validate=False` opt-out for trusted bulk paths |
| `delete(pk, soft=True, user)` | BFS soft-delete with `MAX_CASCADE_DEPTH=10` |

### Page-size cap

`BaseService.list()` silently clamps any `limit` greater than
`max_page_size` (default **100**) and logs a WARNING with the
requested vs capped values. An absent `limit` is set to the ceiling —
unbounded `.all()`-style listings can't be triggered by accident.

Subclasses raise the ceiling per resource:

```python
class ReportService(BaseService[Report]):
    model = Report
    max_page_size = 1000     # this resource needs larger pages
```

We never raise on over-large limits — pagination callers routinely
pass a default `page_size` from request params, and a hard-fail would
convert a config miss into a 500. The WARNING is the contract: anyone
asking for >max_page_size sees it in logs immediately.

### Filter & order allow-lists

```python
class APIKeyService(BaseService[APIKey]):
    model = APIKey
    allowed_filter_fields = frozenset({"is_active", "user"})
    allowed_order_fields  = frozenset({"created_at", "last_used_at"})
```

Without an allow-list, `_validate_filter_keys` and `_validate_order_keys`
are permissive (so the default service stays usable) — set them on any
service that handles untrusted input.

---

## Verb hierarchy (naming convention)

Quoted from the top-level `CLAUDE.md`:

| prefix | tier | example |
|---|---|---|
| `execute_*` | raw SQL primitives (needs an engine) | `execute_query`, `execute_writes` |
| `get_*` | single-entity ORM fetches | `get_by_id`, `get_by_email` |
| `fetch_*` | external-system reads | `fetch_partner_status`, `fetch_s3_object` |

Don't mix verbs at the same tier. Leading underscore means
internal-only to the defining class or module — if a method is called
from a sibling class or another module, drop the underscore.

---

## Validation contract — single source of truth

Pinned by `tests/integration/test_base_service_validation.py`:

| service write | runs `full_clean()` via | bypass |
|---|---|---|
| `create()` | `BaseModel.save()` | not supported |
| `update()` | `BaseModel.save()` | not supported |
| `bulk_create()` | explicit loop | pass `validate=False` |
| direct `instance.save()` | `BaseModel.save()` | pass `skip_validation=True` |

`skip_validation=True` is reserved for fixtures, management commands,
and paths where validation already ran (e.g. the service layer calling
`.save()` a second time). It is **never** correct to use from view or
service code on first-write of user-supplied data.

---

## See also

- [adding-a-new-app.md](adding-a-new-app.md) — checklist form of this
  reference for new domain apps.
- [audit-trail.md](audit-trail.md) — soft-delete cascade and audit
  field propagation.
- [resilience.md](resilience.md) — `@resilient` and registry.
- `apps/core/CLAUDE.md` — module-level conventions for `core`.
