# Design: Subtask 5 — Docker Containerization

**Date:** 2026-04-01
**Branch:** `feature/docker`
**Status:** Approved

> **Note:** This spec supersedes the docker-compose skeleton in `SUBTASK.md`. It adds a `redis` service, proper healthchecks, and `condition: service_healthy` dependencies throughout.

## Overview

Containerize the Breakdown application (FastAPI backend + React/Vite frontend + PostgreSQL + Redis) so the entire stack starts with a single `docker compose up --build`.

## Components

### docker-compose.yml

Four services:

| Service    | Image / Build           | Port (host:container) | Healthcheck                  |
|------------|-------------------------|-----------------------|------------------------------|
| `postgres`  | `postgres:16`           | 5433:5432             | `pg_isready -U breakdown`    |
| `redis`     | `redis:7-alpine`        | internal only         | `redis-cli ping`             |
| `app`       | Build from `.`          | 8000:8000             | `GET /health` → 200          |
| `frontend`  | Build from `./frontend` | 5173:5173             | none                         |

Key `app` environment variables (passed in docker-compose, not from `.env`):
- `DATABASE_URL=postgresql+asyncpg://breakdown:${POSTGRES_PASSWORD:-localpassword}@postgres:5432/breakdown`
- `REDIS_URL=redis://redis:6379`
- `TERSECONTEXT_URL=${TERSECONTEXT_URL:-http://host.docker.internal:8090}`
- `SOURCE_DIRS=/repos`
- `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_CHANNEL`, `DEFAULT_MODEL`

`~/workspaces` on the host is mounted read-only as `/repos` in the app container. In CI environments prefer `${HOME}/workspaces` over `~` for portability.

Relevant YAML snippets (authoritative over SUBTASK.md skeleton):

```yaml
redis:
  image: redis:7-alpine
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5

app:
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
    interval: 10s
    timeout: 5s
    retries: 10
    start_period: 30s   # covers alembic migration time on cold start

frontend:
  depends_on:
    app:
      condition: service_healthy
```

The app healthcheck uses Python's stdlib `urllib` rather than `curl` because `python:3.12-slim` does not include `curl`. No extra apt package is needed.

**External network prerequisite:** The `tersecontext_tersecontext` network must exist before `docker compose up`, otherwise Compose will refuse to start. If TerseContext is not running, create the network manually first:

```bash
docker network create tersecontext_tersecontext 2>/dev/null || true
```

This should be included as step 1 in the README quick start.

### Root Dockerfile — add Alembic files and git

The existing Dockerfile only copies `app/` and `pyproject.toml`. Add:

```dockerfile
COPY alembic.ini .
COPY alembic/ ./alembic/
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
```

`git` is required because `app/routes/repos.py` calls `git` via subprocess inside the container. `python:3.12-slim` does not include it by default.

### app/main.py lifespan — Alembic on startup

Before `seed_admin()`, run migrations using the async-safe form:

```python
import asyncio

proc = await asyncio.create_subprocess_exec("alembic", "upgrade", "head")
await proc.wait()
if proc.returncode != 0:
    raise RuntimeError(f"alembic upgrade head failed with code {proc.returncode}")
```

`subprocess.run` must not be used — it blocks the event loop. The Alembic subprocess inherits the container's environment, so `DATABASE_URL` is available. Outside Docker, the environment must also be fully populated for this to work.

The `alembic.ini` `sqlalchemy.url` is overridden at runtime by `alembic/env.py` via `config.set_main_option`, so no manual editing of `alembic.ini` is needed.

### frontend/Dockerfile

- Base: `node:20-slim`
- `WORKDIR /app`
- Copy `package.json` + `package-lock.json`, run `npm ci`
- Copy source, expose port 5173
- CMD: `npm run dev -- --host` (binds Vite to `0.0.0.0` inside the container)

### frontend/vite.config.ts — environment-aware proxy

The proxy target must differ between containerized and local development. Use a `VITE_API_URL` env variable with a sensible default:

```ts
proxy: {
  '/api': process.env.VITE_API_URL ?? 'http://localhost:8000'
}
```

In `docker-compose.yml`, pass `VITE_API_URL=http://app:8000` to the `frontend` service. Local development (outside Docker) continues to work without any configuration change since the default is `http://localhost:8000`.

### .env

The `.env` file is for local (non-Docker) development only. Copy from `.env.example` and populate:
- `DATABASE_URL=postgresql+asyncpg://breakdown:localpassword@localhost:5433/breakdown`
- `REDIS_URL=redis://localhost:6379`
- `TERSECONTEXT_URL=http://localhost:8090`
- `ANTHROPIC_API_KEY=<real key>`
- Optional: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_CHANNEL`
- `DEFAULT_MODEL=claude-sonnet-4-20250514`

Postgres credentials (`breakdown` / `localpassword`) must match `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` in docker-compose.yml.

### README.md

Update with:
1. **Quick start:**
   ```bash
   docker network create tersecontext_tersecontext 2>/dev/null || true
   cp .env.example .env   # set ANTHROPIC_API_KEY
   docker compose up --build
   ```
2. How to configure `SOURCE_DIRS` (`~/workspaces` on host mounted as `/repos` read-only)
3. TerseContext prerequisite: must be running; `tersecontext_tersecontext` network must exist; repos must be indexed; `TERSECONTEXT_URL` defaults to `http://host.docker.internal:8090`
4. Slack app setup: socket mode, required scopes (`channels:read`, `chat:write`, etc.)
5. API reference: `GET /api/tasks/{id}`
6. Consumer docs: reading from `stream:breakdown-approved` Redis stream

## Data Flow

```
Browser (5173) → Frontend (Vite dev server)
                       ↓ /api/* proxy → http://app:8000
              App (FastAPI :8000)
               ├── PostgreSQL (postgres:5432 internal)
               ├── Redis (redis:6379 internal) → stream:breakdown-approved
               └── TerseContext API (via tersecontext_tersecontext network)
```

## Service Startup Order

1. `postgres` → healthcheck passes (`pg_isready`)
2. `redis` → healthcheck passes (`redis-cli ping`)
3. `app` → runs `alembic upgrade head` → seeds admin → serves on 8000 → healthcheck passes (`GET /health`) — `start_period: 30s` covers migration time
4. `frontend` → Vite dev server with `VITE_API_URL=http://app:8000`

## Error Handling

- Postgres healthcheck with 10 retries before app starts
- Redis healthcheck with 5 retries before app starts
- Alembic failure raises `RuntimeError`, stopping container startup visibly
- `tersecontext_tersecontext` network missing → Compose exits immediately with clear error; README quick start includes `docker network create` guard
- Slack bot failure is caught and logged; app continues without it

## Verification

```bash
docker compose up --build

# Open localhost:5173 — login, submit, review
# Submit a task, wait for research, approve
docker compose exec redis redis-cli XRANGE stream:breakdown-approved - +
# expect: approved bundle
```
