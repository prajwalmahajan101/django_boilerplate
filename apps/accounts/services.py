"""Services for auth-related operations."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.exceptions import InvalidTimezoneError, NoFieldsToUpdateError
from accounts.models import APIKey
from accounts.repositories import UserRepository
from core.base.service import BaseService

__all__ = ["APIKeyService", "UserService"]

logger = logging.getLogger(__name__)


class APIKeyService(BaseService[APIKey]):
    """Service for API-key lifecycle operations.

    Soft-delete inherits from ``BaseService.delete``; ``revoke`` is the
    state-transition path that stamps ``revoked_at`` so
    ``APIKeyAuthentication`` rejects the key on its next use without
    losing the audit row.
    """

    model = APIKey

    @transaction.atomic
    def revoke(self, pk: int, *, user) -> tuple[bool, bool]:
        """Soft-revoke an active API key.

        Acquires a row-level lock before stamping ``revoked_at`` so two
        concurrent revoke requests can't race on the timestamp.

        Returns:
            ``(revoked_now, already_revoked)``:
              * ``(True,  False)`` — this call stamped ``revoked_at``.
              * ``(False, True)``  — the key was already revoked; idempotent.
              * ``(False, False)`` — no active key with that pk; caller
                should return 404.
        """
        api_key = (
            APIKey.objects
            .select_related("user")
            .select_for_update(of=("self",))
            .filter(pk=pk, is_active=True)
            .first()
        )
        if api_key is None:
            return (False, False)
        if api_key.revoked_at is not None:
            return (False, True)
        api_key.revoked_at = timezone.now()
        api_key.updated_by = user
        api_key.save(update_fields=["revoked_at", "updated_at", "updated_by"])
        return (True, False)


class UserService:
    """Service for user profile operations."""

    UPDATABLE_PROFILE_FIELDS = frozenset({"timezone", "first_name", "last_name"})

    def __init__(self, repository: UserRepository | None = None):
        self.repository = repository or UserRepository()

    def update_profile(self, user_id: int, data: dict[str, Any]):
        """Update user profile fields with validation.

        Filters input to allowed fields, validates timezone against
        the IANA database, and delegates persistence to the repository.
        Locking + atomicity now live on ``UserRepository.update`` — see
        ISSUE-008. Don't re-wrap with ``transaction.atomic`` here.
        """
        update_data = {
            k: v for k, v in data.items() if k in self.UPDATABLE_PROFILE_FIELDS
        }

        if not update_data:
            raise NoFieldsToUpdateError()

        if "timezone" in update_data:
            from zoneinfo import available_timezones

            if update_data["timezone"] not in available_timezones():
                raise InvalidTimezoneError()

        return self.repository.update(user_id, update_data)
