"""``api_log`` — end-to-end audit pipeline for inbound + outbound HTTP.

Public surface:

* :func:`log_inbound` — DRF view decorator that audits the request.
* :func:`log_outbound` — service-method decorator that audits the
  outbound HTTP call (consumes metadata published by
  ``resilience_kit.http_client.AsyncAPIClient``).
* :class:`ApiLog` — the audit row model.
* :data:`Direction` — enum of audit directions.

Backend selection is driven by ``API_LOG_BACKEND`` (``orm`` /
``noop``). The Postgres-backed batched writer in the fastapi version
is replaced here with a Django-ORM backend executed off-thread via
the existing :class:`apps.core.dispatch.fire_and_forget.FireAndForgetQueue`
— same back-pressure / drain semantics, idiomatic Django persistence.
"""

default_app_config = "core.api_log.apps.ApiLogConfig"
