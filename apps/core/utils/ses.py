"""SES utilities: send HTML emails via Amazon Simple Email Service."""

from __future__ import annotations

import contextlib
import logging
import mimetypes
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from core.exceptions.infrastructure import (
    ExternalTimeoutError,
    SESException,
    TransientError,
)
from core.utils.aws import get_aws_client
from core.utils.log_sanitization import safe_log_dict
from core.utils.logging import log_duration
from django.conf import settings
from resilience_kit import resilient

logger = logging.getLogger(__name__)

# SES error codes that represent transient failures and should be retried.
# Permanent failures (e.g. ``MessageRejected``, ``MailFromDomainNotVerified``)
# fall through to a non-retryable ``SESException``.
_SES_TRANSIENT_ERROR_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "ServiceUnavailable",
        "ServiceUnavailableException",
        "InternalFailure",
        "InternalServerError",
        "RequestExpired",
        "RequestTimeout",
        "RequestTimeoutException",
    }
)


def _ses_region() -> str | None:
    """Return the SES-specific region override, or None to fall back to AWS_REGION."""
    region = getattr(settings, "SES_REGION", "")
    return region or None


def _sender_domain(sender: str) -> str:
    """Extract the host portion of an email address for Message-ID generation."""
    if "@" in sender:
        return sender.rsplit("@", 1)[-1].strip() or "localhost"
    return "localhost"


def _generate_message_id(sender: str) -> str:
    """Build an RFC 5322 Message-ID using the sender's domain.

    The Message-ID we set on outbound mail is the same value SES delivers
    on the wire (because we use ``send_raw_email``), so it can be stored
    verbatim on ``parent.notes['email_thread_id']`` and reused as
    ``In-Reply-To`` on the next reply with no host-format guessing.
    """
    return f"<{uuid.uuid4().hex}@{_sender_domain(sender)}>"


@dataclass(frozen=True)
class EmailAttachment:
    """A binary attachment for ``send_email``.

    ``data`` is the raw object bytes (already fetched from S3 by the caller —
    we don't accept S3 URIs here so the email layer stays decoupled from the
    storage layer).
    """

    filename: str
    content_type: str
    data: bytes


def _build_attachment_part(att: EmailAttachment):
    """Build an appropriate MIME part for the attachment's MIME type."""
    main, _, sub = att.content_type.partition("/")
    if main == "image" and sub:
        part = MIMEImage(att.data, _subtype=sub)
    elif main == "text":
        part = MIMEText(
            att.data.decode("utf-8", errors="replace"), _subtype=sub or "plain", _charset="utf-8"
        )
    else:
        # Default: application/* and everything else lands here.
        sub = sub or mimetypes.guess_extension(att.content_type) or "octet-stream"
        part = MIMEApplication(att.data, _subtype=sub.lstrip("."))
    part.add_header("Content-Disposition", "attachment", filename=att.filename)
    return part


def _classify_client_error(exc: ClientError) -> Exception:
    """Map a botocore ``ClientError`` to a retryable or permanent exception.

    Retryable SES errors (throttling, internal failures, request expiry)
    surface as ``TransientError`` so the ``@resilient`` decorator's
    tenacity-backed retry loop kicks in. Everything else is a permanent
    ``SESException`` and propagates to the caller without retry.
    """
    code = ""
    with contextlib.suppress(AttributeError):
        code = exc.response.get("Error", {}).get("Code", "")
    if code in _SES_TRANSIENT_ERROR_CODES:
        return TransientError(f"SES transient failure ({code}): {exc}")
    return SESException(f"SES request failed ({code or 'Unknown'}): {exc}")


@resilient("ses")
def send_email(
    *,
    recipient_emails: list[str],
    subject: str,
    body_html: str,
    sender_email: str | None = None,
    cc_emails: list[str] | None = None,
    bcc_emails: list[str] | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    attachments: Iterable[EmailAttachment] | None = None,
) -> dict[str, Any]:
    """Send an HTML email via AWS SES (always as raw MIME).

    Building the MIME message ourselves means the ``Message-ID`` header on
    the wire is deterministic — we generate it, attach it, and return it
    so callers can persist it for later threading.

    Args:
        recipient_emails: List of TO addresses.
        subject: Email subject line.
        body_html: HTML content for the email body.
        sender_email: Sender address. Defaults to ``settings.SES_SENDER_EMAIL``.
            Must be a verified identity in SES.
        cc_emails: Optional list of CC addresses (added to envelope AND visible header).
        bcc_emails: Optional list of BCC addresses (envelope only, no header).
        in_reply_to: Optional Message-ID (with brackets) to thread under.
        references: Optional ordered list of prior Message-IDs forming the
            conversation chain. Combined with ``in_reply_to`` per RFC 5322.

    Returns:
        Dict with:
          * ``message_id`` — SES internal MessageId token (boto response).
          * ``message_id_header`` — the ``Message-ID`` header we placed on
            the wire. **This** is the value to store for future threading.
          * ``response`` — raw boto3 response dict.

    Raises:
        SESException: Permanent failures (rejected message, unverified
            identity, missing sender configuration). Not retried.
        TransientError: Throttling, internal SES failures, or network
            errors. Retried automatically by ``@resilient``.
    """
    sender = sender_email or getattr(settings, "SES_SENDER_EMAIL", "")
    if not sender:
        raise SESException("No sender email configured. Set SES_SENDER_EMAIL or pass sender_email.")

    cc_emails = cc_emails or []
    bcc_emails = bcc_emails or []
    attachment_list = list(attachments or [])
    envelope_recipients = list(recipient_emails) + list(cc_emails) + list(bcc_emails)
    message_id_header = _generate_message_id(sender)

    if attachment_list:
        # Build a multipart/mixed envelope with the HTML body as the first
        # part. We keep the body as a plain MIMEText (HTML) child so the
        # existing single-part branch remains the default — this keeps
        # downstream tests that parse the body unchanged when there are
        # no attachments.
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        for att in attachment_list:
            msg.attach(_build_attachment_part(att))
    else:
        msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipient_emails)
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id_header
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        chain = list(references or [])
        if in_reply_to not in chain:
            chain.append(in_reply_to)
        msg["References"] = " ".join(chain)

    logger.info(
        "Sending email via SES",
        extra=safe_log_dict(
            recipient_count=len(recipient_emails),
            has_cc=bool(cc_emails),
            has_bcc=bool(bcc_emails),
            attachment_count=len(attachment_list),
            subject=subject,
            sender=sender,
            threaded=bool(in_reply_to),
            message_id_header=message_id_header,
        ),
    )

    with log_duration(
        logger,
        "ses_send_email",
        metric=True,
        recipient_count=len(recipient_emails),
        attachment_count=len(attachment_list),
    ):
        try:
            client = get_aws_client("ses", region=_ses_region())
            response = client.send_raw_email(
                Source=sender,
                Destinations=envelope_recipients,
                RawMessage={"Data": msg.as_string()},
            )
        except ClientError as exc:
            logger.error(
                "Failed to send email via SES",
                extra=safe_log_dict(
                    recipient_count=len(recipient_emails),
                    subject=subject,
                    error=str(exc),
                    error_code=exc.response.get("Error", {}).get("Code", "")
                    if hasattr(exc, "response")
                    else "",
                ),
                exc_info=True,
            )
            raise _classify_client_error(exc) from exc
        except BotoCoreError as exc:
            # Network / connection / serialization issues — always transient.
            logger.error(
                "Transient SES failure",
                extra=safe_log_dict(
                    recipient_count=len(recipient_emails),
                    subject=subject,
                    error=str(exc),
                ),
                exc_info=True,
            )
            raise TransientError(f"SES transport failure: {exc}") from exc

    ses_message_id = response.get("MessageId", "")
    logger.info(
        "Email sent via SES",
        extra=safe_log_dict(
            ses_message_id=ses_message_id,
            message_id_header=message_id_header,
            recipient_count=len(recipient_emails),
            subject=subject,
        ),
    )

    return {
        "message_id": ses_message_id,
        "message_id_header": message_id_header,
        "response": response,
    }


# Re-export for callers that catch by type (kept stable).
__all__ = [
    "EmailAttachment",
    "ExternalTimeoutError",
    "SESException",
    "TransientError",
    "send_email",
]
