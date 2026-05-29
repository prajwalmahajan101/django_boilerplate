# Authentication & Authorization

## Overview

The Co-Lending Gateway uses a layered auth system:

1. **Authentication**: Google OAuth2 -> JWT tokens (primary), API keys (system-to-system)
2. **Authorization**: Role-Based Access Control (RBAC) with Resource/Action permissions

## Authentication Flow

### Google OAuth2

```
Frontend                  Gateway                    Google
   │                         │                         │
   │  1. Redirect to Google  │                         │
   │─────────────────────────┼────────────────────────>│
   │                         │                         │
   │  2. User consents       │                         │
   │<────────────────────────┼─────────────────────────│
   │                         │                         │
   │  3. POST /accounts/google/                        │
   │     {code, redirect_uri}│                         │
   │────────────────────────>│                         │
   │                         │  4. Exchange code        │
   │                         │─────────────────────────>│
   │                         │                         │
   │                         │  5. User info            │
   │                         │<─────────────────────────│
   │                         │                         │
   │  6. {access, refresh,   │                         │
   │      user}              │                         │
   │<────────────────────────│                         │
```

1. Frontend redirects user to Google OAuth consent screen
2. User grants permission, Google redirects back with authorization code
3. Frontend sends the code to `POST /api/accounts/google/`
4. Gateway exchanges code for Google tokens via django-allauth
5. Gateway fetches user info, creates/updates User record
6. Gateway returns JWT access + refresh tokens with user profile

### JWT Tokens

| Token | Lifetime | Purpose |
|---|---|---|
| Access | 1 hour | API request authentication (Bearer header) |
| Refresh | 7 days | Obtain new access token |

**Token rotation**: When refreshing, the old refresh token is blacklisted and a new pair is issued. This prevents token replay.

**Usage:**
```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGci...
```

**Signing**: Tokens are signed with `JWT_SIGNING_KEY` (separate from `SECRET_KEY` to limit blast radius if compromised). Falls back to `SECRET_KEY` if not set.

### API Keys

For system-to-system authentication (CI/CD, partner callbacks, automated scripts):

- Created via Django Admin (one-time display of raw key)
- Stored encrypted (Fernet AES-128) in the database
- Indexed by 8-character prefix for fast lookup
- Tied to a User -- inherits that user's RBAC permissions

**Usage:**
```
Authorization: Api-Key clg_abc12345...
```

**Lifecycle:**
1. Admin creates API key via Django Admin panel
2. Raw key displayed once (copy it immediately)
3. Only the encrypted version and prefix are stored
4. `last_used_at` is updated on each use
5. Deactivate by setting `is_active = False`

## Authorization (RBAC)

### Model

```
User ──M:N── Role ──M:N── Permission
                              │
                         ┌────┴────┐
                         │Resource │ Action │
                         ├─────────┤────────┤
                         │ACCOUNT  │ CREATE │
                         │PARTNER  │ READ   │
                         │QUERY    │ UPDATE │
                         │LEAD     │ DELETE │
                         │FIELD_   │ PUSH   │
                         │ CONFIG  │        │
                         │API_KEY  │        │
                         └─────────┴────────┘
```

### Resources

| Resource | Scope |
|---|---|
| `ACCOUNT` | User management, profiles |
| `PARTNER` | Partner CRUD, push operations |
| `QUERY` | Query and remark management |
| `LEAD` | Lead data access |
| `FIELD_CONFIG` | Field sections and definitions |
| `API_KEY` | API key management |
| `ASSIGNMENT_RULE` | Query auto-assignment rules and pool membership |

### Actions

| Action | Meaning |
|---|---|
| `CREATE` | Create new records |
| `READ` | View/list records |
| `UPDATE` | Modify existing records |
| `DELETE` | Remove records |
| `PUSH` | Push data to external partners |

### How It Works

1. **View declares requirements**: Each view sets `resource` and `action` attributes.

   ```python
   class PartnerListCreateView(APIView):
       resource = Resource.PARTNER

       def initial(self, request, *args, **kwargs):
           self.action = Action.READ if request.method == "GET" else Action.CREATE
           super().initial(request, *args, **kwargs)
   ```

2. **Permission class checks**: `HasResourcePermission` walks User -> Roles -> Permissions.

   ```python
   # In HasResourcePermission.has_permission():
   user.roles.filter(
       permissions__resource=view.resource,
       permissions__action=view.action
   ).exists()
   ```

3. **Per-request caching**: Permission results are cached on `request._permission_cache` to avoid repeated DB queries within the same request.

4. **Superuser bypass**: Users with any role where `is_superuser_role = True` skip all permission checks.

### Default Role

Roles with `is_default = True` are automatically assigned to new users on signup. This ensures every user has a baseline set of permissions.

### Django Auth Backend

`RBACBackend` in `accounts/backends.py` bridges Django's permission system with the custom RBAC model. It maps Django permission strings (e.g., `"partner.read"`) to Resource/Action enum lookups.

## Session Security

| Setting | Value | Purpose |
|---|---|---|
| `JWT_AUTH_HTTPONLY` | True | Prevent XSS access to tokens |
| `JWT_AUTH_SAMESITE` | Lax | CSRF protection for cookie-based auth |
| `JWT_AUTH_SECURE` | True (prod) | Cookies only over HTTPS |
| `SESSION_COOKIE_HTTPONLY` | True | Protect session cookie from JS |
| `CSRF_COOKIE_HTTPONLY` | True | Protect CSRF cookie from JS |

## OAuth Configuration

### Google OAuth Setup

Required environment variables:
```
GOOGLE_OAUTH2_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH2_CLIENT_SECRET=your-client-secret
GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS=http://localhost:3000/auth/callback,https://app.example.com/auth/callback
```

The redirect URI allowlist is fail-closed: if `GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS` is empty, all redirect URIs are rejected.

### Allauth Configuration

- Email-based accounts (not username)
- Email verification: mandatory for password signup, not required for Google OAuth
- Automatic account linking by email
- Custom adapter: `accounts.adapters.CustomAccountAdapter`
