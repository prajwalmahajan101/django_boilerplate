"""DB-level constraint tests for the accounts app.

Pins the CheckConstraints introduced by the "Model Design & Data Integrity"
sweep against the ``Permission`` model. Pattern #69 (TextChoices + paired
CheckConstraint) — closes the gap where ``Resource`` and ``Action`` enums had
only application-side ``choices`` validation.

Permission is plain ``models.Model`` (apps/accounts/models.py:17), so
``Model.save()`` does NOT call ``full_clean()`` by default — a direct save
hits the DB and the CHECK fires without needing ``skip_validation``.
"""

from __future__ import annotations

from accounts.models import Permission
from django.db import IntegrityError, transaction
from django.test import TestCase


class PermissionEnumConstraintTests(TestCase):
    """ck_permission_resource and ck_permission_action — pattern #69."""

    def test_invalid_resource_rejected_by_db(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Permission.objects.create(resource="bogus_resource", action="create")

    def test_invalid_action_rejected_by_db(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Permission.objects.create(resource="account", action="bogus_action")

    def test_valid_pair_accepted(self):
        # Sanity: a known-good (resource, action) pair saves cleanly. Use
        # ``get_or_create`` so the test passes whether seed migrations
        # already created the row or not. The point is to confirm the
        # CHECK constraints don't reject valid enum values.
        permission, _ = Permission.objects.get_or_create(resource="account", action="read")
        self.assertEqual(permission.resource, "account")
        self.assertEqual(permission.action, "read")
