# Deployment Guide

## Environments

| Environment | Config | Infra | Purpose |
|---|---|---|---|
| Local | `docker-compose.yml` | Single Docker network | Development with hot-reload |
| Dev/Staging | `docker-compose.dev.yml` | EC2 + ECR images | Testing and integration |
| Production | Custom (same patterns) | AWS infrastructure | Live traffic |

## Local Development

### Start

```bash
docker compose up --build
```

### Services

| Service | Image | Port | Notes |
|---|---|---|---|
| web | Built from Dockerfile | 8000 | `runserver` with volume mounts for hot-reload |
| nginx | nginx:alpine | 80 | Rate limiting zones, security headers |
| db | postgres:16-alpine | 5432 | Volume: `postgres_data`, health check: pg_isready |
| valkey | valkey/valkey:8-alpine | 6379 | maxmemory 256mb, LRU eviction, AOF persistence |
| rabbitmq | rabbitmq:3.13-management | 5672, 15672 | Management UI at 15672 |
| celery_worker | Built from Dockerfile | -- | threads pool, concurrency=4, 3 queues |
| celery_beat | Built from Dockerfile | -- | DatabaseScheduler |
| flower | Built from Dockerfile | 5555 | Basic auth (admin/changeme) |

### Volumes

- `postgres_data` -- Database persistence
- `valkey_data` -- Cache persistence (AOF)
- `rabbitmq_data` -- Message broker persistence
- `static_files` -- Collected static files (shared between web and nginx)

### Stop

```bash
docker compose down          # Stop services, keep volumes
docker compose down -v       # Stop services, remove volumes (full reset)
```

## Dev/EC2 Deployment

### Architecture

Two-tier Nginx with ECR image pulls:

```
Internet
    │
    ▼
┌──────────────────────────────────┐
│ Gateway Nginx (port 80/443)      │
│ - TLS termination (TLS 1.2/1.3) │
│ - HTTP→HTTPS redirect            │
│ - Security headers (HSTS, CSP)   │
│ - Route: /api/, /admin/, /flower/│
└──────────┬───────────────────────┘
           │
    ┌──────▼──────┐
    │ Backend     │
    │ Nginx       │
    │ (port 80)   │
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │ Gunicorn    │
    │ (4 workers, │
    │  60s timeout)│
    └─────────────┘
```

### Prerequisites

1. AWS ECR repository with built images
2. EC2 instance with Docker and Docker Compose
3. SSL certificates for gateway
4. Environment file with secrets

### Deploy

```bash
# Set environment
export ECR_REGISTRY=123456789.dkr.ecr.ap-south-1.amazonaws.com
export IMAGE_TAG=dev

# Login to ECR
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin $ECR_REGISTRY

# Deploy
docker compose -f docker-compose.dev.yml up -d

# Run migrations
docker compose -f docker-compose.dev.yml exec web python manage.py migrate
```

### Services

| Service | Image Source | Notes |
|---|---|---|
| web | ECR | Gunicorn, health check (HTTP 200 on /api/health/) |
| backend-nginx | nginx:alpine | Proxies to web, depends on health check |
| gateway | nginx:alpine | TLS, port 80/443, includes gateway-common.conf |
| valkey | valkey/valkey:8-alpine | Password-protected (`--requirepass`) |
| celery_worker | ECR | Threads pool, configurable concurrency |
| celery_beat | ECR | DatabaseScheduler |
| flower | ECR | localhost:5555 only (not exposed externally) |

### Networking

All services communicate on the `app-net` Docker network. Only the gateway exposes ports to the host (80, 443). Rename the network in `docker-compose.yml` to match your project before deploy.

### Health Checks

| Service | Check | Interval |
|---|---|---|
| web | `curl -sf http://localhost:8000/api/health/` | 30s |
| valkey | `valkey-cli -a $VALKEY_PASSWORD ping` | 10s |
| backend-nginx | Depends on web health | -- |

## Docker Image

### Multi-Stage Build

```dockerfile
# Stage 1: Builder
FROM python:3.12-slim AS builder
# Install build deps (gcc, libpq-dev)
# Create virtualenv at /opt/venv
# Install Python packages from requirements/*.txt

# Stage 2: Runtime
FROM python:3.12-slim
# Copy venv from builder (no build tools in final image)
# Install runtime libs only (libpq5, postgresql-client)
# Create non-root user (appuser, UID 1000)
# Collect static files at build time
# Expose 8000
```

### Build Arguments

| ARG | Default | Description |
|---|---|---|
| `REQUIREMENTS_FILE` | `requirements/dev.txt` | Which requirements to install |

### Build for Production

```bash
docker build \
  --build-arg REQUIREMENTS_FILE=requirements/prod.txt \
  -t app:latest .
```

### Push to ECR

```bash
# Tag
docker tag app:latest \
  $ECR_REGISTRY/app:$IMAGE_TAG

# Push
docker push $ECR_REGISTRY/app:$IMAGE_TAG
```

## Nginx Configuration

### Local (`nginx/default.conf`)

Rate limiting zones:
- `/api/accounts/` -- 5 req/s (burst 10)
- `/api/` -- 30 req/s (burst 50)
- `/admin/` -- 10 req/s (burst 20)

Set `NUM_PROXIES=1` in the app environment whenever traffic enters through nginx — DRF reads `REST_FRAMEWORK["NUM_PROXIES"]` to decide how many `X-Forwarded-For` hops to trust when bucketing throttles. Behind ALB + nginx use `NUM_PROXIES=2`. Without it every anon client shares `REMOTE_ADDR = <proxy-ip>` and `BurstThrottle` / `AuthThrottle` / `AuthEndpointThrottle` collapse into a single bucket.

Security headers on all responses:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Content-Security-Policy: self + cdn.jsdelivr.net
- Permissions-Policy: camera/microphone/geolocation blocked

### Gateway (`nginx/gateway.dev.conf` + `nginx/gateway-common.conf`)

- HTTP -> HTTPS redirect (301)
- TLS 1.2/1.3, HIGH ciphers only
- HSTS: max-age=31536000, includeSubDomains, preload
- Routing: /api/, /admin/, /flower/ (WebSocket upgrade), /static/
- Timeouts: 30s connect, 90s read/send

### Security Headers (`nginx/security-headers.conf`)

Reusable snippet included via `include /etc/nginx/snippets/security-headers.conf`:
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

## Production Considerations

### Secrets Management

- Use AWS Secrets Manager (`AWS_SECRET_NAME`) for all sensitive values
- Never commit `.env` files with real credentials
- `FIELD_ENCRYPTION_KEY` should be separate from `SECRET_KEY`
- `JWT_SIGNING_KEY` should be separate from `SECRET_KEY`
- Rotate keys by updating Secrets Manager and redeploying

### Scaling

- **Gunicorn workers**: Set `GUNICORN_WORKERS` based on CPU cores (2 * cores + 1)
- **Celery concurrency**: Set `CELERY_WORKER_CONCURRENCY` based on task I/O profile
- **Valkey**: Configure `maxmemory` and eviction policy for expected cache size
- **PostgreSQL**: Tune `DB_CONN_MAX_AGE` and connection pool settings
- **External SQL sources** (if you wire any): tune `<NAME>_DB_POOL_SIZE` / `<NAME>_DB_MAX_OVERFLOW` per source. Pattern lives in `core/utils/db.py`.

### Monitoring

| Tool | Purpose | Access |
|---|---|---|
| Sentry | Error tracking + performance | Set `SENTRY_DSN` |
| Flower | Celery task monitoring | localhost:5555 (not exposed) |
| CloudWatch | Centralized logging | Set `CLOUDWATCH_ENABLED=TRUE` |
| Health endpoint | Load balancer checks | `GET /api/health/` |
| Readiness endpoint | Dependency checks | `GET /api/readiness/` |

### Backup

- PostgreSQL: Regular pg_dump or AWS RDS snapshots
- Valkey: AOF persistence enabled, periodic RDB snapshots
- RabbitMQ: Messages are transient; persistent tasks use django-celery-results (DB)

### Security Checklist

- [ ] `DEBUG=False`
- [ ] `SECRET_KEY` is unique and strong (50+ random characters)
- [ ] `FIELD_ENCRYPTION_KEY` is set (separate from SECRET_KEY)
- [ ] `JWT_SIGNING_KEY` is set (separate from SECRET_KEY)
- [ ] `ALLOWED_HOSTS` is restricted to actual domains
- [ ] `CORS_ALLOWED_ORIGINS` lists only trusted origins (no wildcard)
- [ ] `POSTGRES_PASSWORD` is not the default
- [ ] `VALKEY_PASSWORD` is set
- [ ] `RABBITMQ_USER` and `RABBITMQ_PASSWORD` are not defaults
- [ ] `FLOWER_USER` and `FLOWER_PASSWORD` are changed
- [ ] SSL certificates are valid and auto-renewed
- [ ] AWS Secrets Manager is used for all credentials
- [ ] Sentry DSN is configured for error tracking
- [ ] Firewall rules restrict access to internal ports (5432, 6379, 5672, 5555)
