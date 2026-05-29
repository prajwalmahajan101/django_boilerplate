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

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Permission


class PermissionEnumConstraintTests(TestCase):
    """ck_permission_resource and ck_permission_action — pattern #69."""

    def test_invalid_resource_rejected_by_db(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Permission.objects.create(resource="bogus_resource", action="create")

    def test_invalid_action_rejected_by_db(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Permission.objects.create(resource="account", action="bogus_action")

    def test_valid_pair_accepted(self):
        # Sanity: a known-good (resource, action) saves cleanly. The earlier
        # seed migrations (0002/0003/0004/0012/0014) populate most of the
        # grid — use ``get_or_create`` so the test passes whether the row
        # already exists or not. The point is to confirm the CHECK doesn't
        # reject valid enum values.
        permission, _ = Permission.objects.get_or_create(
            resource="lead", action="push"
        )
        self.assertEqual(permission.resource, "lead")
        self.assertEqual(permission.action, "push")
