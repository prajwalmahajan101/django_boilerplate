"""Pin the kit-exception → boilerplate-envelope bridge invariant.

Closes M7 §3.6. The :class:`BaseCustomError` ↔ :class:`ResilienceKitError`
bridge in :mod:`core.base.exception` and the ``from_exception`` projection
in :mod:`core.exceptions.handler` together promise that **every kit
exception renders through our DRF handler as a valid boilerplate
envelope**. There was no test pinning that promise — a kit release
adding a new exception class (or a refactor of the handler) could
silently break one branch.

:func:`resilience_kit.testing.verify_envelope_contract` enumerates every
kit exception class in the ``exceptions`` argument (which defaults to
the full public set the kit ships with), runs each through the
handler we hand it, validates the result against the envelope schema,
and collects every failure into a single ``AssertionError`` — so a
future kit release adding three exceptions failing the contract
shows us all three in one test run instead of one-at-a-time.

A future kit release adding an exception subclass will start to
``RateLimitError``-shape (i.e. extending the default ``exceptions``
sequence): if it breaks our envelope shape, this test goes red and
points us at the bridge or projection layer that needs a tweak.
"""

from __future__ import annotations

import pytest
from core.exceptions.handler import api_exception_handler
from core.responses.envelope_schema import ResponseEnvelope
from resilience_kit.testing import verify_envelope_contract


@pytest.mark.django_db(transaction=False)
def test_kit_envelope_contract() -> None:
    """Every public kit exception → valid boilerplate envelope.

    The kit exposes ``DEFAULT_EXCEPTIONS`` indirectly through
    ``verify_envelope_contract``'s default ``exceptions`` arg.
    """

    def _handle(exc):
        response = api_exception_handler(exc, context={})
        # The DRF Response wraps the dict body; we hand the dict over so
        # ``envelope_schema`` validates the envelope shape itself, not
        # the DRF Response wrapper.
        return response.data

    verify_envelope_contract(
        handler=_handle,
        envelope_schema=ResponseEnvelope.model_validate,
    )
