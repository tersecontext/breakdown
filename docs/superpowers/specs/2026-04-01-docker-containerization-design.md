# Design: Subtask 5 — Docker Containerization

**Date:** 2026-04-01
**Branch:** `feature/docker`
**Status:** Approved

## Overview

Containerize the Breakdown application (FastAPI backend + React/Vite frontend + PostgreSQL + Redis) so the entire stack starts with a single `docker compose up --build`.

## Components

### docker-compose.yml

Four services:

| Service    | Image / Build        | Port      | Notes                                      |
|------------|----------------------|-----------|--------------------------------------------|
| `postgres`  | `postgres:16`        | 5433:5432 | Healthcheck; persistent `pgdata` volume    |
| `redis`     | `redis:7-alpine`     | 6379      | Own service; not shared with TerseContext  |
| `app`       | Build from `.`       | 8000:8000 | Depends on postgres (healthy) and redis; also joins `tersecontext_tersecontext` external network for TC API access |
| `frontend`  | Build from `./frontend` | 5173:5173 | Depends on app                            |

The `tersecontext_tersecontext` external network is only for reaching the TerseContext API. Redis is local.

### frontend/Dockerfile

- Base: `node:20-slim`
- `WORKDIR /app`
- Copy `package.json` + `package-lock.json`, run `npm ci`
- Copy source, expose port 5173
- CMD: `npm run dev -- --host` (binds Vite to `0.0.0.0`)

### app/main.py lifespan — Alembic on startup

Before `seed_admin()`, run `alembic upgrade head` via `subprocess.run` so migrations apply automatically on container start.

### .env

Copy `.env.example` to `.env`, populated with Docker-appropriate values:
- `DATABASE_URL` pointing to `localhost:5433`
- `REDIS_URL` pointing to `localhost:6379`
- Real `ANTHROPIC_API_KEY`
- Optional Slack tokens

### README.md

Update with:
- Quick start: `cp .env.example .env && docker compose up --build`
- How to configure `SOURCE_DIRS` (mounted as `/repos` read-only)
- TerseContext prerequisite (must be running, repos indexed, `tersecontext_tersecontext` network must exist)
- Slack app setup (socket mode, required scopes)
- API reference: `GET /api/tasks/{id}`
- Consumer docs: reading from `stream:breakdown-approved` Redis stream

## Data Flow

```
Browser (5173) → Frontend (Vite dev server)
                       ↓ /api/* proxy
              App (FastAPI :8000)
               ├── PostgreSQL (5432 internal)
               ├── Redis (6379 internal) → stream:breakdown-approved
               └── TerseContext API (via tersecontext_tersecontext network)
```

## Error Handling

- Postgres healthcheck (`pg_isready`) with 10 retries before app starts
- Alembic failure on startup surfaces as a non-zero exit, stopping the container visibly
- Slack bot failure is caught and logged; app continues without it

## Testing / Verification

```bash
docker compose up --build
# localhost:5173 — login, submit, review
# Submit a task, wait for research, approve
docker compose exec redis redis-cli XRANGE stream:breakdown-approved - +
# expect: approved bundle
```
