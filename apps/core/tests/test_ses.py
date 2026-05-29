"""Tests for the SES utility — raw MIME assembly and error classification.

These tests pin the contract that:
  * ``send_email`` always uses ``send_raw_email`` and supplies a
    deterministic ``Message-ID:`` header that matches the value returned
    to the caller as ``message_id_header``.
  * Threading headers (``In-Reply-To`` and ``References``) are present
    when ``in_reply_to`` is supplied, and absent when it isn't.
  * ``Cc:`` is rendered as a visible header AND CC recipients land on
    the SES envelope.
  * Botocore errors are classified into ``TransientError`` (so
    ``@resilient("ses")`` retries) vs ``SESException`` (permanent).
"""

from __future__ import annotations

from email import message_from_string
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError
from django.test import TestCase, override_settings

from core.exceptions.infrastructure import SESException, TransientError
from core.utils.ses import send_email


_SES_SETTINGS = dict(
    SES_SENDER_EMAIL="ops@optimoloan.com",
    AWS_REGION="ap-south-1",
)


def _stub_client(message_id: str = "ses-msg-1") -> MagicMock:
    client = MagicMock()
    client.send_raw_email.return_value = {"MessageId": message_id}
    return client


def _captured_mime(client: MagicMock):
    """Return the parsed MIME message that was handed to ``send_raw_email``."""
    raw = client.send_raw_email.call_args.kwargs["RawMessage"]["Data"]
    return message_from_string(raw)


@override_settings(**_SES_SETTINGS)
class SendEmailRawMIMETest(TestCase):
    @patch("core.utils.ses.get_aws_client")
    def test_message_id_header_is_returned_and_matches_wire(self, mock_get_client):
        client = _stub_client()
        mock_get_client.return_value = client

        result = send_email(
            recipient_emails=["partner@example.com"],
            subject="Hello",
            body_html="<p>hi</p>",
        )

        mime = _captured_mime(client)
        self.assertTrue(result["message_id_header"].startswith("<"))
        self.assertTrue(result["message_id_header"].endswith("@optimoloan.com>"))
        # Deterministic: the header on the wire IS the value returned.
        self.assertEqual(mime["Message-ID"], result["message_id_header"])
        self.assertEqual(result["message_id"], "ses-msg-1")

    @patch("core.utils.ses.get_aws_client")
    def test_cc_rendered_in_header_and_envelope(self, mock_get_client):
        client = _stub_client()
        mock_get_client.return_value = client

        send_email(
            recipient_emails=["to@example.com"],
            cc_emails=["cc1@example.com", "cc2@example.com"],
            bcc_emails=["bcc@example.com"],
            subject="cc test",
            body_html="<p>x</p>",
        )

        mime = _captured_mime(client)
        self.assertEqual(mime["Cc"], "cc1@example.com, cc2@example.com")
        # BCC must NOT appear in headers.
        self.assertIsNone(mime["Bcc"])
        # Envelope must include cc + bcc.
        envelope = client.send_raw_email.call_args.kwargs["Destinations"]
        self.assertIn("cc1@example.com", envelope)
        self.assertIn("bcc@example.com", envelope)

    @patch("core.utils.ses.get_aws_client")
    def test_in_reply_to_sets_threading_headers_with_chain(self, mock_get_client):
        client = _stub_client()
        mock_get_client.return_value = client

        send_email(
            recipient_emails=["to@example.com"],
            subject="Re: thread",
            body_html="<p>x</p>",
            in_reply_to="<root@partner.com>",
            references=["<root@partner.com>", "<reply1@optimoloan.com>"],
        )

        mime = _captured_mime(client)
        self.assertEqual(mime["In-Reply-To"], "<root@partner.com>")
        # References must accumulate the chain (caller's list preserved).
        self.assertEqual(
            mime["References"],
            "<root@partner.com> <reply1@optimoloan.com>",
        )

    @patch("core.utils.ses.get_aws_client")
    def test_no_threading_headers_on_first_send(self, mock_get_client):
        client = _stub_client()
        mock_get_client.return_value = client

        send_email(
            recipient_emails=["to@example.com"],
            subject="First",
            body_html="<p>x</p>",
        )

        mime = _captured_mime(client)
        self.assertIsNone(mime["In-Reply-To"])
        self.assertIsNone(mime["References"])


@override_settings(**_SES_SETTINGS)
class SendEmailErrorClassificationTest(TestCase):
    @patch("core.utils.ses.get_aws_client")
    def test_throttling_client_error_becomes_transient(self, mock_get_client):
        client = MagicMock()
        client.send_raw_email.side_effect = ClientError(
            error_response={"Error": {"Code": "Throttling", "Message": "slow down"}},
            operation_name="SendRawEmail",
        )
        mock_get_client.return_value = client

        with self.assertRaises(TransientError):
            send_email(
                recipient_emails=["to@example.com"],
                subject="x",
                body_html="<p>x</p>",
            )

    @patch("core.utils.ses.get_aws_client")
    def test_message_rejected_is_permanent_ses_exception(self, mock_get_client):
        client = MagicMock()
        client.send_raw_email.side_effect = ClientError(
            error_response={"Error": {"Code": "MessageRejected", "Message": "nope"}},
            operation_name="SendRawEmail",
        )
        mock_get_client.return_value = client

        with self.assertRaises(SESException):
            send_email(
                recipient_emails=["to@example.com"],
                subject="x",
                body_html="<p>x</p>",
            )

    @patch("core.utils.ses.get_aws_client")
    def test_botocore_network_error_is_transient(self, mock_get_client):
        client = MagicMock()
        client.send_raw_email.side_effect = EndpointConnectionError(
            endpoint_url="https://email.ap-south-1.amazonaws.com"
        )
        mock_get_client.return_value = client

        with self.assertRaises(TransientError):
            send_email(
                recipient_emails=["to@example.com"],
                subject="x",
                body_html="<p>x</p>",
            )

    def test_missing_sender_raises_ses_exception(self):
        with override_settings(SES_SENDER_EMAIL=""):
            with self.assertRaises(SESException):
                send_email(
                    recipient_emails=["to@example.com"],
                    subject="x",
                    body_html="<p>x</p>",
                )
