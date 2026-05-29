"""Tests for ``core.tasks``."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from core.tasks import enqueue, register_task, registered_tasks
from core.tasks.registry import _reset_registry


class RegisterTaskTests(TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def tearDown(self) -> None:
        _reset_registry()

    def test_registers_with_custom_name(self) -> None:
        @register_task(name="tests.dummy")
        def dummy() -> str:
            return "ok"

        self.assertIn("tests.dummy", registered_tasks())

    def test_bare_decorator_uses_qualname(self) -> None:
        @register_task
        def another_dummy() -> str:
            return "ok"

        names = list(registered_tasks().keys())
        self.assertTrue(any("another_dummy" in n for n in names))


class EnqueueTests(TestCase):
    @override_settings(CELERY_TASK_DEFAULT_QUEUE="my-queue")
    def test_enqueue_forwards_to_celery_send_task(self) -> None:
        with patch("config.celery.app.send_task") as send_task:
            enqueue("tests.dummy", 1, 2, x="y")
            send_task.assert_called_once_with(
                "tests.dummy",
                args=(1, 2),
                kwargs={"x": "y"},
                queue="my-queue",
                countdown=None,
                eta=None,
            )
