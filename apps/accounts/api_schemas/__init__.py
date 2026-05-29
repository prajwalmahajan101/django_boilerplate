"""Public OpenAPI schema surface for the accounts app.

Re-exports the endpoint-schema decorators so consumers continue to use
``from accounts.api_schemas import <name>`` unchanged across the split into
per-resource sub-modules.
"""

from accounts.api_schemas.api_key import api_key_delete_schema, api_key_revoke_schema
from accounts.api_schemas.auth import (
    google_login_schema,
    logout_schema,
    token_refresh_schema,
)
from accounts.api_schemas.user import me_get_schema, me_patch_schema

__all__ = [
    "api_key_delete_schema",
    "api_key_revoke_schema",
    "google_login_schema",
    "logout_schema",
    "me_get_schema",
    "me_patch_schema",
    "token_refresh_schema",
]
