"""Shared enums for the project.

`Resource` and `Action` form the RBAC vocabulary checked by
`HasResourcePermission`. Extend `Resource` with one entry per domain
noun your app owns. Keep `Action` stable across domains so role
definitions stay portable.
"""

from django.db import models


class Resource(models.TextChoices):
    """RBAC resource vocabulary; extend per-domain via ``register_resource``."""

    ACCOUNT = "account", "Account"
    ROLE = "role", "Role"
    API_KEY = "api_key", "API Key"


class Action(models.TextChoices):
    """RBAC action vocabulary; stable across domains so roles stay portable."""

    CREATE = "create", "Create"
    READ = "read", "Read"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
