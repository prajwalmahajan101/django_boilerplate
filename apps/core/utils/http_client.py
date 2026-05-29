"""Generic HTTP client with per-call retry via Tenacity.

Provides a reusable ``make_http_request`` function that wraps the
``requests`` library with:

- Per-call retry count (supports dynamic config, e.g. per-partner)
- Exponential backoff between retries
- Structured error mapping to infrastructure exceptions
- Connection pooling via a module-level ``requests.Session``
- Sanitized logging (no secrets leak into logs)

Usage::

    from core.utils.http_client import make_http_request

    response = make_http_request(
        method="POST",
        url="https://partner.example.com/api/leads",
        headers={"X-Tenant": "colender"},
        json_body={"name": "John"},
        max_attempts=3,
    )
    print(response.status_code, response.body)
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.exceptions.infrastructure import ExternalTimeoutError, TransientError
from core.exceptions.repository import InvalidOutboundURLError
from core.utils.log_sanitization import safe_log_dict

logger = logging.getLogger(__name__)


def _safe_host(url: str) -> str:
    """Extract the hostname from *url* for use in exception messages.

    Callers see only the hostname (no port, no path, no query). The full
    URL is still recorded in the structured log via ``safe_log_dict``.
    This prevents internal addresses and ports from leaking into HTTP
    response bodies surfaced to API consumers.
    """
    try:
        return urlparse(url).hostname or "external service"
    except Exception:
        return "external service"


def _assert_url_allowlisted(url: str) -> None:
    """Reject outbound URLs whose hostname is not in OUTBOUND_URL_ALLOWLIST.

    Defence-in-depth alongside ``_assert_public_url``. The SSRF guard
    blocks private IPs; the allow-list blocks legitimate public hosts
    we never intended to call (data-exfiltration via a misconfigured
    partner URL, accidental call to a typo'd domain, etc.).

    Allow-list entries are matched as:
      * ``*`` — wildcard, allow anything (default in local/dev).
      * ``example.com`` — exact host match.
      * ``.example.com`` — suffix match (any subdomain).

    Empty list = no allow-list configured = permissive. Prod and UAT
    should set ``OUTBOUND_URL_ALLOWLIST`` explicitly per environment.
    """
    allow = list(getattr(settings, "OUTBOUND_URL_ALLOWLIST", []) or [])
    if not allow or "*" in allow:
        return
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise InvalidOutboundURLError("URL has no hostname.")
    for entry in allow:
        entry = entry.lower()
        if entry.startswith("."):
            if host == entry[1:] or host.endswith(entry):
                return
        elif host == entry:
            return
    raise InvalidOutboundURLError(
        f"Outbound URL host '{host}' is not in OUTBOUND_URL_ALLOWLIST."
    )


def _assert_public_url(url: str, *, strict: bool = True) -> None:
    """Reject URLs that resolve to non-public IP space (SSRF defense).

    Checks every address returned by ``getaddrinfo`` — a single hostname
    can resolve to multiple IPs, and any one pointing at internal space
    (RFC1918, loopback, link-local, reserved, unspecified, multicast)
    is grounds for rejection. Also rejects non-http(s) schemes.

    Modes:
      - ``strict=True`` (default, used by ``make_http_request``): an
        unresolvable hostname is a rejection. At call time we cannot
        verify the target, and the request would fail anyway.
      - ``strict=False`` (model validators on admin save): an
        unresolvable hostname is *accepted*. DNS may be transiently
        flaky and we don't want to block legitimate partner config at
        save time. The strict HTTP-call path still protects the actual
        outbound request.

    Disabled when ``settings.SSRF_BLOCK_PRIVATE_IPS`` is falsy — set
    ``False`` in tests that use localhost mock servers.

    Callers that originate from admin-configured trust boundaries (e.g. a
    ``Partner`` row) bypass this check by passing ``trusted=True`` to
    ``make_http_request``. The trust boundary is the Partner config layer,
    not this validator.

    Raises:
        InvalidOutboundURLError: registered at HTTP 400 in handler.py.
    """
    if not getattr(settings, "SSRF_BLOCK_PRIVATE_IPS", True):
        return

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidOutboundURLError(
            f"URL scheme '{parsed.scheme}' is not allowed (only http/https)."
        )
    host = parsed.hostname
    if not host:
        raise InvalidOutboundURLError("URL has no hostname.")

    # Literal IPs short-circuit DNS resolution entirely.
    try:
        literal = ipaddress.ip_address(host)
        addrs = {str(literal)}
    except ValueError:
        try:
            addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except socket.gaierror as exc:
            if strict:
                raise InvalidOutboundURLError(
                    f"URL hostname '{host}' could not be resolved."
                ) from exc
            # Lenient: accept. Save-time validators don't block on
            # transient DNS failure; the HTTP call-path (strict) will
            # catch private-IP resolution at request time.
            logger.info(
                "SSRF validator: %s did not resolve (strict=False, accepting).",
                host,
            )
            return

    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
        ):
            raise InvalidOutboundURLError(
                f"URL resolves to a non-public address ({addr})."
            )

# Cache built retry decorators by max_attempts to preserve Tenacity state.
# Locked via double-checked locking — matches the _engine_cache pattern
# in apps/core/utils/db.py and the thread-safety contract in
# docs/thread-safety.md.
_retry_cache: dict[int, Any] = {}
_retry_cache_lock = threading.Lock()

# Thread-local session for connection pooling (one per thread).
_thread_local = threading.local()


def _get_session() -> requests.Session:
    """Return a thread-local requests.Session (one per thread)."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


@dataclass(frozen=True)
class HttpResponse:
    """Structured response from an HTTP call.

    ``body`` is the parsed JSON / text by default, or the raw response
    ``bytes`` when the call was made with ``raw_bytes=True`` — used for binary
    downloads (e.g. documents) where JSON/text parsing would corrupt the
    payload.
    """

    status_code: int
    body: dict | str | bytes | None
    headers: dict


def make_http_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
    auth: tuple[str, str] | None = None,
    max_attempts: int = 3,
    trusted: bool = False,
    raw_bytes: bool = False,
) -> HttpResponse:
    """Make an HTTP request with automatic retry on transient failures.

    Args:
        method: HTTP method (GET, POST, PUT, PATCH, DELETE).
        url: Target URL.
        headers: Request headers.
        json_body: JSON-serializable request body.
        timeout: Request timeout in seconds.
        auth: Optional ``(username, password)`` tuple for HTTP Basic Auth.
        max_attempts: Number of attempts (1 = no retry).
        raw_bytes: When ``True``, return the raw response ``bytes`` in
            ``HttpResponse.body`` instead of parsing JSON/text — for binary
            downloads. The allowlist + retry path is unchanged.
        trusted: Skip the SSRF private-IP check when the URL originates from
            an admin-configured trust boundary (e.g. a ``Partner`` row). The
            Partner config layer is the trust boundary for the *private-IP*
            question — this function should not second-guess it. Never pass
            ``True`` for URLs derived from user input.

            ``trusted`` does **not** opt out of ``OUTBOUND_URL_ALLOWLIST``.
            The allowlist asks a different question — "did the deploy
            operator sanction this destination?" — which is still valid
            for admin-configured partner URLs. A compromised admin
            changing a ``Partner.api_endpoint`` to an unsanctioned host
            should still be blocked by the allowlist.

    Returns:
        An :class:`HttpResponse` with status code, parsed body, and headers.

    Raises:
        TransientError: On HTTP 5xx responses or connection errors.
        ExternalTimeoutError: On request timeouts.
    """
    if max_attempts < 1:
        max_attempts = 1

    # SSRF (private-IP) check is the only thing ``trusted`` opts out of.
    if not trusted:
        _assert_public_url(url)
    # The allowlist is orthogonal to SSRF — it enforces the deploy-time
    # sanctioned-destination list and must apply to trusted call sites too.
    _assert_url_allowlisted(url)

    decorator = _retry_cache.get(max_attempts)
    if decorator is None:
        with _retry_cache_lock:
            decorator = _retry_cache.get(max_attempts)
            if decorator is None:
                decorator = retry(
                    stop=stop_after_attempt(max_attempts),
                    wait=wait_exponential(min=1, max=10),
                    retry=retry_if_exception_type(
                        (TransientError, ExternalTimeoutError)
                    ),
                    reraise=True,
                )
                _retry_cache[max_attempts] = decorator

    return decorator(_do_request)(
        method, url, headers, json_body, timeout, auth, raw_bytes
    )


def _do_request(
    method: str,
    url: str,
    headers: dict[str, str] | None,
    json_body: dict[str, Any] | None,
    timeout: int,
    auth: tuple[str, str] | None,
    raw_bytes: bool = False,
) -> HttpResponse:
    """Execute a single HTTP request (called by the retry wrapper)."""
    logger.info(
        "HTTP request: %s %s",
        method,
        url,
        extra=safe_log_dict(method=method, url=url),
    )

    try:
        resp = _get_session().request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            timeout=timeout,
            auth=auth,
        )
    except requests.Timeout as exc:
        logger.warning(
            "HTTP request timed out: %s %s",
            method,
            url,
            extra=safe_log_dict(method=method, url=url, timeout=timeout),
        )
        raise ExternalTimeoutError(
            f"Request to {_safe_host(url)} timed out after {timeout}s"
        ) from exc
    except requests.ConnectionError as exc:
        # Log the exception class only, not str(exc). requests.ConnectionError
        # messages commonly contain HTTPConnectionPool(host='<internal-ip>',
        # port=<port>) which leaks infrastructure topology into log
        # aggregation. Operators correlate via request_id in the log record.
        logger.warning(
            "HTTP connection error: %s %s",
            method,
            url,
            extra=safe_log_dict(method=method, url=url, error_class=type(exc).__name__),
        )
        raise TransientError(
            f"Connection error contacting {_safe_host(url)}"
        ) from exc

    body = resp.content if raw_bytes else _parse_response_body(resp)

    logger.info(
        "HTTP response: %s %s -> %d",
        method,
        url,
        resp.status_code,
        extra=safe_log_dict(method=method, url=url, status_code=resp.status_code),
    )

    if resp.status_code >= 500:
        raise TransientError(
            f"Server error from {_safe_host(url)}: HTTP {resp.status_code}"
        )

    return HttpResponse(
        status_code=resp.status_code,
        body=body,
        headers=dict(resp.headers),
    )


def _parse_response_body(resp: requests.Response) -> dict | str | None:
    """Parse response body as JSON if possible, otherwise return text."""
    content_type = resp.headers.get("Content-Type", "")
    if not resp.content:
        return None
    if "application/json" in content_type:
        try:
            return resp.json()
        except ValueError:
            return resp.text
    return resp.text
