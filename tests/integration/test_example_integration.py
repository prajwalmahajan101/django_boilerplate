"""Example integration test — DB allowed, no HTTP client.

Demonstrates the integration-layer contract: hit the real database via
the ORM / service layer, verify the row state, but stay within a
single process.
"""

from __future__ import annotations


def test_user_factory_persists_to_db(user_factory):
    """The factory creates a real row that round-trips through the ORM."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = user_factory(email="integration@example.com")

    fetched = User.objects.get(pk=user.pk)
    assert fetched.email == "integration@example.com"
    assert fetched.is_active is True


def test_password_hash_matches_set_password(user_factory):
    """The factory's password post-generation hook uses the auth hasher."""
    user = user_factory(password="s3cret!")
    assert user.check_password("s3cret!") is True
    assert user.check_password("wrong") is False
