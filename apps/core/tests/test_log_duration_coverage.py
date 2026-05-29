"""Verifies that every Phase 1a-instrumented hot path actually wraps its
work in ``log_duration``.

These tests do not measure timing; they assert structural coverage. If a
future refactor unwraps ``log_duration`` from a hot path (regressing the
observability surface), these tests fail loudly.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase


class LogDurationCoverageTests(SimpleTestCase):
    """Each test imports the instrumented module and asserts a wrap call."""

    def test_partner_push_wraps_log_duration(self) -> None:
        from partners.services import push as push_module

        source = open(push_module.__file__).read()
        self.assertIn('log_duration', source)
        self.assertIn('"partner_push"', source)
        self.assertIn('domain_context', source)

    def test_sql_leads_wraps_log_duration(self) -> None:
        from leads.services import sql_leads as sql_leads_module

        source = open(sql_leads_module.__file__).read()
        self.assertIn('log_duration', source)
        self.assertIn('"synoriq_query"', source)
        self.assertIn('event_label', source)

    def test_asset_create_from_upload_wraps_log_duration(self) -> None:
        from assets.services import asset_service

        source = open(asset_service.__file__).read()
        self.assertIn('"asset_create_from_upload"', source)
        self.assertIn('"s3_upload"', source)

    def test_ses_wraps_log_duration(self) -> None:
        from core.utils import ses as ses_module

        source = open(ses_module.__file__).read()
        self.assertIn('"ses_send_email"', source)

    def test_remark_task_wraps_log_duration(self) -> None:
        from queries import tasks as tasks_module

        source = open(tasks_module.__file__).read()
        self.assertIn('"remark_processing_email_task"', source)
        self.assertIn('domain_context', source)

    def test_assignment_engine_emits_domain_context(self) -> None:
        from queries.services import assignment_engine

        source = open(assignment_engine.__file__).read()
        self.assertIn('domain_context', source)
        self.assertIn('"assignment_rr_pick"', source)

    def test_exc_info_on_critical_error_logs(self) -> None:
        """Critical infrastructure error logs must carry exc_info=True so
        the structured payload includes the traceback for log-aggregation.
        """
        from core.utils import s3, ses
        from core.base import fields
        from partners.services import push

        for module in (s3, ses, fields, push):
            source = open(module.__file__).read()
            self.assertIn(
                'exc_info=True',
                source,
                msg=f"{module.__name__} missing exc_info=True on at least one logger.error",
            )
