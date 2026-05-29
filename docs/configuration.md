# Configuration Reference

## Settings Architecture

Configuration is loaded dynamically by `config/settings/__init__.py`:

1. Load `.env.{DJANGO_ENV}` file via python-dotenv
2. Import `config.settings.base` (core settings)
3. For dev/prod: fetch secrets from AWS Secrets Manager and overlay onto environment
4. Import `config.settings.{DJANGO_ENV}` (environment-specific overrides)
5. Configure logging (JSON structured output)
6. Configure Sentry (optional, if `SENTRY_DSN` is set)

`DJANGO_ENV` is required and has no default. The application will not start without it.

## Environment Modules

| Module | `DJANGO_ENV` | Key Differences |
|---|---|---|
| `local` | `local` | DEBUG=True, throttling disabled, console email, no SSL |
| `dev` | `dev` | AWS Secrets Manager, proxy header trust, HTTPS via proxy |
| `prod` | `prod` | HSTS, SSL redirect, secure cookies, strict validation |
| `test` | `test` | PostgreSQL, in-memory cache, eager Celery, AllowAny |

### Production Validations

Production settings enforce at startup:
- `VALKEY_CACHE_URL` must be set (no in-memory cache fallback)
- `CELERY_BROKER_URL` must be set
- `POSTGRES_PASSWORD` must not be the default value
- `CORS_ALLOW_ALL_ORIGINS` must be False
- `DEBUG` is forced to False

## Environment Variables

### Django Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `DJANGO_ENV` | Yes | -- | Environment: `local`, `dev`, `prod`, `test` |
| `SECRET_KEY` | Yes | -- | Django secret key for signing |
| `FIELD_ENCRYPTION_KEY` | Required in dev/prod | `SECRET_KEY` (local/test only) | Separate key for EncryptedCharField (partner credentials). Missing in `dev`/`prod` raises `ImproperlyConfigured` at startup; fallback to `SECRET_KEY` applies only under `DEBUG=True`. |
| `DEBUG` | No | `False` | Debug mode (forced False in prod) |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `CSRF_TRUSTED_ORIGINS` | No | -- | Comma-separated trusted origins for CSRF |

### Database (Primary)

| Variable | Required | Default | Description |
|---|---|---|---|
| `POSTGRES_DB` | No | `app` | Database name |
| `CELERY_APP_NAME` | No | `app` | Celery application name (worker / queue identity) |
| `POSTGRES_USER` | No | `postgres` | Database user |
| `POSTGRES_PASSWORD` | No | `postgres` | Database password |
| `POSTGRES_HOST` | No | `db` | Database host |
| `POSTGRES_PORT` | No | `5432` | Database port |
| `DB_CONN_MAX_AGE` | No | `600` | Connection max age (seconds) |

### External SQL sources (optional, via SQLAlchemy)

`core/utils/db.py` is wired to read from any external Postgres source
(legacy systems, analytics warehouses, partner-owned read replicas) via
SQLAlchemy with engine caching, 5s connect timeout, and 30s statement
timeout. Wire your own env-var prefixes (`<NAME>_DB_HOST`, `<NAME>_DB_PORT`,
…) when you add such a source. Documented pattern in
[development.md](development.md#external-sql-sources) and
[scalability.md](scalability.md).

### Cache (Valkey)

| Variable | Required | Default | Description |
|---|---|---|---|
| `VALKEY_CACHE_URL` | Prod: Yes | `valkey://valkey:6379/2` | Default cache URL |
| `VALKEY_RATE_LIMIT_URL` | No | `valkey://valkey:6379/3` | Rate limit cache URL |
| `VALKEY_PASSWORD` | No | -- | Valkey password (dev/prod) |

### Celery

| Variable | Required | Default | Description |
|---|---|---|---|
| `CELERY_BROKER_URL` | Prod: Yes | -- | RabbitMQ broker URL (`amqp://user:pass@host:port//`) |
| `CELERY_RESULT_BACKEND` | No | `django-db` | Result backend (django-db or redis URL) |
| `CELERY_WORKER_CONCURRENCY` | No | `4` | Worker concurrency |

### RabbitMQ

| Variable | Required | Default | Description |
|---|---|---|---|
| `RABBITMQ_USER` | No | `guest` | RabbitMQ username |
| `RABBITMQ_PASSWORD` | No | `guest` | RabbitMQ password |

### Authentication

| Variable | Required | Default | Description |
|---|---|---|---|
| `JWT_SIGNING_KEY` | Required in dev/prod | `SECRET_KEY` (local/test only) | Dedicated JWT signing key. Missing in `dev`/`prod` raises `ImproperlyConfigured` at startup. |
| `GOOGLE_OAUTH2_CLIENT_ID` | Yes (if OAuth) | -- | Google OAuth client ID |
| `GOOGLE_OAUTH2_CLIENT_SECRET` | Yes (if OAuth) | -- | Google OAuth client secret |
| `GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS` | No | -- | Comma-separated allowed redirect URIs |

### CORS

| Variable | Required | Default | Description |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | No | `http://localhost:3000` | Comma-separated allowed origins |

If set to `*`, enables `CORS_ALLOW_ALL_ORIGINS=True` (blocked in production).

### Rate Limiting

| Variable | Required | Default | Description |
|---|---|---|---|
| `RATE_LIMIT_ANON` | No | `100/hour` | Anonymous user rate |
| `RATE_LIMIT_USER` | No | `1000/hour` | Authenticated user rate |
| `RATE_LIMIT_ADMIN` | No | `5000/hour` | Admin user rate |
| `RATE_LIMIT_BURST` | No | `10/second` | Burst rate (all users) |
| `RATE_LIMIT_GLOBAL` | No | `10000/minute` | Global rate limit |
| `RATE_LIMIT_FAIL_OPEN` | No | `true` | Allow requests when rate limiter fails |
| `RATE_LIMIT_ENABLE_HEADERS` | No | `true` | Include X-RateLimit-* headers |

### Circuit Breaker

| Variable | Required | Default | Description |
|---|---|---|---|
| `CIRCUIT_BREAKER_VALKEY_ALIAS` | No | `rate_limit` | Valkey cache alias for CB state |
| `CIRCUIT_BREAKER_KEY_PREFIX` | No | `cb` | Key prefix in Valkey |
| `CIRCUIT_BREAKER_FAIL_OPEN` | No | `true` | Allow requests when CB infra fails |

### Resilience Defaults

| Variable | Required | Default | Description |
|---|---|---|---|
| `RESILIENCE_CB_FAIL_MAX` | No | `5` | Failures before circuit opens |
| `RESILIENCE_CB_RESET_TIMEOUT` | No | `30` | Seconds before half-open |
| `RESILIENCE_RETRY_MAX_ATTEMPTS` | No | `3` | Max retry attempts |
| `RESILIENCE_RETRY_WAIT_MIN` | No | `1` | Min backoff (seconds) |
| `RESILIENCE_RETRY_WAIT_MAX` | No | `10` | Max backoff (seconds) |

#### Per-service breakers

Register breakers in `apps/core/apps.py::CoreConfig._register_resilience_services`. Two reference services are pre-wired in the boilerplate and serve as templates for domain code:

| Service | `fail_max` | `reset_timeout` | Excluded exceptions | Notes |
|---|---|---|---|---|
| `s3` | 5 | 30 s | `S3NotFoundError` | 404 = absent object (cache miss), not S3 outage. |
| `ses` | 5 | 60 s | — | Every failure is infra; nothing excluded. |

Add a row when you register a new service — the table is the operator's
lookup, the registration call is the source of truth.

### Logging

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | No | `INFO` | Root log level |
| `LOG_SANITIZE_ENABLED` | No | `true` | Enable log sanitization |
| `LOG_MASK_PATTERN` | No | (sensitive regex) | Regex for fields to mask |
| `LOG_MAX_STRING_LENGTH` | No | `1000` | Max string length in logs |
| `LOG_MAX_DICT_KEYS` | No | `50` | Max dict keys in logs |
| `LOG_MAX_LIST_ITEMS` | No | `20` | Max list items in logs |
| `LOG_EXCLUDED_FIELDS` | No | -- | Comma-separated fields to exclude |

### AWS

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_SECRET_NAME` | Dev/Prod | -- | AWS Secrets Manager secret name |
| `AWS_REGION` | No | `ap-south-1` | AWS region |

### Monitoring

| Variable | Required | Default | Description |
|---|---|---|---|
| `SENTRY_DSN` | No | -- | Sentry DSN for error tracking |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.1` | Sentry performance sample rate |
| `APP_VERSION` | No | -- | Application version tag for Sentry |
| `CLOUDWATCH_ENABLED` | No | `FALSE` | Enable CloudWatch logging |
| `CLOUDWATCH_LOG_GROUP` | No | -- | CloudWatch log group name |

### Proxy

| Variable | Required | Default | Description |
|---|---|---|---|
| `USE_X_FORWARDED_FOR` | No | `false` | Trust X-Forwarded-For header |
| `SSRF_BLOCK_PRIVATE_IPS` | No | `true` | Block outbound HTTP requests to private / loopback / link-local / reserved IPs. Enforced inside `core.utils.http_client.make_http_request` via `_assert_public_url`. Automatically disabled in `test` settings so the test suite can hit local mock servers; keep `true` in dev/prod. |

### Valkey Sentinel (prepared, not deployed)

| Variable | Required | Default | Description |
|---|---|---|---|
| `VALKEY_SENTINEL_HOSTS` | No | `""` | Comma-separated `host:port` pairs. When set, the cache + broker clients switch from a direct `redis://` URL to a Sentinel-aware connection pool. See [scalability.md](scalability.md#5-sentinel-aware-client-config). |
| `VALKEY_SENTINEL_MASTER_NAME` | If `VALKEY_SENTINEL_HOSTS` is set | `""` | Logical master name registered with the Sentinel cluster. |

### Observability / Metrics

| Variable | Required | Default | Description |
|---|---|---|---|
| `METRICS_ENABLED` | No | `false` | Flip to `true` once `prometheus-client` is confirmed importable. While `false`, `/api/metrics` returns HTTP 503 with body `metrics exporter not configured`. See [observability.md](observability.md) for the full activation procedure and the cardinality contract. |
| `METRICS_ALLOWED_IPS` | No | `127.0.0.1` | Comma-separated IP / CIDR allow-list for `/api/metrics`. Source IPs outside the list get HTTP 403 (intentionally distinct from 503 — a misconfigured scraper diagnosing its own failure needs to tell the two cases apart). |

### Docker / Deployment

| Variable | Required | Default | Description |
|---|---|---|---|
| `ECR_REGISTRY` | Deployment | -- | AWS ECR registry URL |
| `IMAGE_TAG` | Deployment | `dev` | Docker image tag |
| `GUNICORN_WORKERS` | No | `4` | Gunicorn worker count |
| `WEB_PORT` | No | `8000` | Web server port |
| `VALKEY_PORT` | No | `6379` | Valkey port |
| `RABBITMQ_PORT` | No | `5672` | RabbitMQ AMQP port |
| `RABBITMQ_MGMT_PORT` | No | `15672` | RabbitMQ management port |
| `FLOWER_USER` | No | `admin` | Flower basic auth user |
| `FLOWER_PASSWORD` | No | `changeme` | Flower basic auth password |

## AWS Secrets Manager Integration

For `dev` and `prod` environments, secrets are loaded from AWS Secrets Manager:

1. Set `AWS_SECRET_NAME` in the `.env` file
2. The settings loader fetches the secret (JSON) from AWS
3. Secret values are overlaid onto `os.environ`
4. `.env` values serve as fallbacks for any keys not in the secret

This means production secrets (database passwords, API keys, etc.) never need to exist in `.env` files on deployed machines.

## Settings Precedence

From highest to lowest priority:

1. OS environment variables
2. AWS Secrets Manager values (dev/prod only)
3. `.env.{DJANGO_ENV}` file values
4. Django settings defaults

## Field-encryption key rotation

`FIELD_ENCRYPTION_KEY` is the symmetric Fernet key used by `EncryptedCharField` (`apps/core/base/fields.py`). It is read once per process and cached via `lru_cache(maxsize=1)`, and rotation today requires brief downtime — there is **no multi-key reader window**. This is a deliberate trade-off until production traffic exists; see "When to add the multi-key reader" below.

### When to rotate

- Suspected compromise of the current key (anything from "AWS access logs show a leak" to "an engineer with key access has left the company").
- Scheduled rotation per a compliance policy (e.g. SOC 2 `CC6.7` review).

### Affected columns

One column holds ciphertext under this key today. A rotation must re-encrypt every row:

- `APIKey.encrypted_key` — `apps/accounts/models.py` (issued API keys; keys are also recoverable via re-issue if rotation goes wrong).

Add additional `EncryptedCharField` columns to this list as new ones land.

### Procedure (downtime-based)

1. **Stop writers.** Bring `web` and `celery_worker` down (and any management commands that call services). Reads can stay up if you want — the rotation script writes in `transaction.atomic` blocks, but eliminating concurrent writers removes the only race window.
   ```
   docker compose stop web celery_worker celery_beat
   ```
2. **Generate the new key** (32 random URL-safe bytes, base64-encoded — exactly the Fernet shape):
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. **Re-encrypt every encrypted row** with a one-shot script. Run it inside the existing `celery_worker` container so it has the same image/dependencies as production:
   ```
   docker exec -e DJANGO_ENV=prod \
     -e FIELD_ENCRYPTION_KEY=<old-key> \
     -e FIELD_ENCRYPTION_KEY_NEW=<new-key> \
     co-lending-gateway-celery_worker-1 \
     python manage.py shell -c "$(cat <<'PY'
   import os
   from cryptography.fernet import Fernet
   from django.db import transaction
   from accounts.models import APIKey
   from partners.models import Partner

   old = Fernet(os.environ['FIELD_ENCRYPTION_KEY'].encode())
   new = Fernet(os.environ['FIELD_ENCRYPTION_KEY_NEW'].encode())

   def reencrypt(model, field):
       with transaction.atomic():
           for row in model.objects.all():
               raw = row.__dict__[field]  # already-decrypted plaintext
               row.__dict__[field] = raw  # forces re-encrypt on save
               row.save(update_fields=[field, 'updated_at'])

   reencrypt(Partner, 'auth_cred')
   reencrypt(APIKey, 'encrypted_key')
   PY
   )"
   ```
   The script reads each row through `EncryptedCharField`'s descriptor (which decrypts via the *old* key cached in this process), then re-saves it (the descriptor encrypts via the *same* old key in this process — that's why the script's process must be torn down and a new one started under the new key). **This script must be run twice for that reason — once under the OLD key to gather plaintext into a temporary table, then once under the NEW key to re-write.** The single-process form above is incorrect; see "Limitations" below.
4. **Swap the env var.** Update `FIELD_ENCRYPTION_KEY` in AWS Secrets Manager (`AWS_SECRET_NAME` for the env). New value takes effect on next process start.
5. **Restart writers.**
   ```
   docker compose start web celery_worker celery_beat
   ```
6. **Verify** by reading any encrypted row through the API or the admin — a successful round-trip confirms the new key is in use. If decryption raises `DecryptionError`, the key in the env doesn't match what was used to encrypt — roll back the env var to the old key, investigate.

### Limitations of the current procedure

- **The single-process form of step 3 above does NOT work** as written — `_get_fernet()` caches a single key per process and the descriptor uses the same cached key for both decrypt-on-read and encrypt-on-write. A correct in-process rotation requires the multi-key reader (option below). The pragmatic procedure today is: dump plaintext under the old key (manual `psql` decrypt or Django shell), kill the process, restart with the new key, write plaintext back. That's the runbook ops should rehearse on `dev` *before* using it in `prod`.
- The Fernet ciphertext format does NOT include a key identifier — there is no way to look at a stored value and know which key encrypted it. Rotation is therefore all-or-nothing per column.

### When to add the multi-key reader

Add the multi-key reader (`OLD_FIELD_ENCRYPTION_KEYS` setting + a `from_db_value` that walks the list) when **either** condition holds:

- Production traffic makes a downtime rotation cost meaningful customer impact (rough heuristic: more than ~$1k/min of revenue or any contract with an SLA tighter than the rotation window).
- A compliance regime requires zero-downtime rotation as part of the control framework.

Until then, a documented downtime procedure (this section) is the right size — building and maintaining a multi-key code path that nobody exercises is its own carrying cost. Re-evaluate after the first paying customer goes live.
