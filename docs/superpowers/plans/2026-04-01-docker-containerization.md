# Docker Containerization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the Breakdown stack so `docker compose up --build` starts all services with no other setup beyond filling in `.env`.

**Architecture:** Four services — `postgres`, `redis`, `app` (FastAPI), `frontend` (Vite dev server) — wired together via Docker Compose healthcheck dependencies. Alembic migrations run on app startup. The app joins an external `tersecontext_tersecontext` network for TerseContext API access.

**Tech Stack:** Docker Compose v2, Python 3.12-slim, node:20-slim, postgres:16, redis:7-alpine, Alembic, Vite 8

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `Dockerfile` | Modify | Add `alembic.ini`, `alembic/`, and `git` apt package |
| `app/main.py` | Modify | Run `alembic upgrade head` in lifespan before `seed_admin()` |
| `tests/test_main.py` | Create | Test alembic migration step |
| `frontend/Dockerfile` | Create | Vite dev server container |
| `frontend/vite.config.ts` | Modify | Use `VITE_API_URL` env var for proxy target |
| `docker-compose.yml` | Create | Four-service compose definition |
| `.env` | Create | Local dev env file (not committed) |
| `README.md` | Modify | Docker quick start and full configuration docs |

---

## Task 1: Update root Dockerfile

**Files:**
- Modify: `Dockerfile`

The current Dockerfile only copies `app/` and `pyproject.toml`. The image needs `alembic.ini` + `alembic/` for migrations, and `git` for `app/routes/repos.py` which calls git via subprocess.

- [ ] **Step 1: Read current Dockerfile**

```bash
cat Dockerfile
```

- [ ] **Step 2: Add alembic files and git to Dockerfile**

After the `COPY app/ ./app/` line, add:

```dockerfile
COPY alembic.ini .
COPY alembic/ ./alembic/
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
```

Full resulting Dockerfile:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY app/ ./app/
COPY alembic.ini .
COPY alembic/ ./alembic/

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Verify build succeeds**

```bash
docker build -t breakdown-test .
```

Expected: `Successfully built ...` with no errors. If `apt-get` fails, check internet connectivity.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: add alembic migrations and git to app Docker image"
```

---

## Task 2: Add Alembic migration to app startup

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_main.py`

The lifespan currently calls `seed_admin()` directly. On a cold database, `seed_admin()` will fail because the `users` table doesn't exist yet. We add `alembic upgrade head` first.

- [ ] **Step 1: Write the failing test**

Create `tests/test_main.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_migrations


@pytest.mark.asyncio
async def test_run_migrations_success():
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await run_migrations()

    mock_exec.assert_called_once_with("alembic", "upgrade", "head")


@pytest.mark.asyncio
async def test_run_migrations_failure_raises():
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=1)
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="alembic upgrade head failed"):
            await run_migrations()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_main.py -v
```

Expected: `ImportError` or `AttributeError` — `run_migrations` does not exist yet.

- [ ] **Step 3: Extract `run_migrations` and update lifespan in app/main.py**

Add the `run_migrations` function and call it at the top of the lifespan, before `seed_admin()`:

```python
async def run_migrations() -> None:
    proc = await asyncio.create_subprocess_exec("alembic", "upgrade", "head")
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed with code {proc.returncode}")
```

And in the lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    await seed_admin()
    # ... rest unchanged
```

Add `import asyncio` at the top of `app/main.py` (it's already there if not — check first).

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_main.py -v
```

Expected:
```
tests/test_main.py::test_run_migrations_success PASSED
tests/test_main.py::test_run_migrations_failure_raises PASSED
```

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass (or same failures as before this change).

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: run alembic migrations on app startup"
```

---

## Task 3: Create frontend/Dockerfile

**Files:**
- Create: `frontend/Dockerfile`

Vite's dev server binds to `127.0.0.1` by default. `--host` makes it bind to `0.0.0.0` so it's reachable from outside the container.

- [ ] **Step 1: Create frontend/Dockerfile**

```dockerfile
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
```

- [ ] **Step 2: Verify the image builds**

```bash
docker build -t frontend-test frontend/
```

Expected: `Successfully built ...`. If `npm ci` fails, check that `frontend/package-lock.json` exists (it does — confirmed earlier).

- [ ] **Step 3: Commit**

```bash
git add frontend/Dockerfile
git commit -m "feat: add frontend Docker image for Vite dev server"
```

---

## Task 4: Update Vite proxy to use VITE_API_URL

**Files:**
- Modify: `frontend/vite.config.ts`

The current proxy hardcodes `http://localhost:8000`. Inside the container, `localhost` is the container itself, not the `app` service. We use an env variable so local dev (outside Docker) still works without changes.

- [ ] **Step 1: Update frontend/vite.config.ts**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.VITE_API_URL ?? 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 2: Verify local dev still works (optional manual check)**

If you have Node available locally:
```bash
cd frontend && npm run dev
```
Expected: Vite starts, proxy target is `http://localhost:8000` (default).

- [ ] **Step 3: Commit**

```bash
git add frontend/vite.config.ts
git commit -m "feat: make Vite proxy target configurable via VITE_API_URL"
```

---

## Task 5: Create docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

This is the core deliverable. Pay careful attention to:
- `condition: service_healthy` on all `depends_on` — plain `depends_on` only waits for container start, not readiness
- App healthcheck uses Python stdlib `urllib` (no `curl` in slim image)
- `VITE_API_URL` passed to frontend so proxy hits `app:8000`
- `tersecontext_tersecontext` is external — must exist before `docker compose up`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: breakdown
      POSTGRES_USER: breakdown
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-localpassword}
    ports:
      - "5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U breakdown"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://breakdown:${POSTGRES_PASSWORD:-localpassword}@postgres:5432/breakdown
      REDIS_URL: redis://redis:6379
      TERSECONTEXT_URL: ${TERSECONTEXT_URL:-http://host.docker.internal:8090}
      SOURCE_DIRS: /repos
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      SLACK_BOT_TOKEN: ${SLACK_BOT_TOKEN:-}
      SLACK_APP_TOKEN: ${SLACK_APP_TOKEN:-}
      SLACK_CHANNEL: ${SLACK_CHANNEL:-tc-tasks}
      DEFAULT_MODEL: ${DEFAULT_MODEL:-claude-sonnet-4-20250514}
    volumes:
      - ${HOME}/workspaces:/repos:ro
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
      start_period: 30s
    networks:
      - default
      - tersecontext_tersecontext

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    environment:
      VITE_API_URL: http://app:8000
    depends_on:
      app:
        condition: service_healthy

volumes:
  pgdata:

networks:
  tersecontext_tersecontext:
    external: true
```

- [ ] **Step 2: Create the external network if it doesn't exist**

```bash
docker network create tersecontext_tersecontext 2>/dev/null || true
```

Expected: either `<network-id>` (created) or an error message ending in "already exists" (fine).

- [ ] **Step 3: Validate compose file syntax**

```bash
docker compose config --quiet
```

Expected: exits with code 0 (no output means valid). If it errors, check YAML indentation.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose with postgres, redis, app, and frontend services"
```

---

## Task 6: Create .env from .env.example

**Files:**
- Create: `.env` (not committed — already in .gitignore or should be)

- [ ] **Step 1: Verify .env is gitignored**

```bash
grep -E "^\.env$|^\.env " .gitignore 2>/dev/null || echo "NOT IN GITIGNORE"
```

If `NOT IN GITIGNORE`, add `.env` to `.gitignore` before proceeding:
```bash
echo ".env" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore .env"
```

- [ ] **Step 2: Copy .env.example to .env**

```bash
cp .env.example .env
```

- [ ] **Step 3: Set ANTHROPIC_API_KEY in .env**

Edit `.env` and replace `sk-...` with the real API key. The `.env` file is only used for local (non-Docker) development. Docker Compose reads variables from the shell environment or a `.env` file at the project root for `${VAR}` substitution in `docker-compose.yml` — so `ANTHROPIC_API_KEY` must be set here or exported in the shell.

---

## Task 7: Update README.md

**Files:**
- Modify: `README.md`

Replace the current "Setup" section with Docker-first instructions. Keep the existing stack description.

- [ ] **Step 1: Update README.md**

Replace the existing `## Setup` section with:

```markdown
## Quick Start (Docker)

**Prerequisites:** Docker with Compose v2, TerseContext running with repos indexed.

```bash
# 1. Create the external network (needed even if TerseContext isn't running)
docker network create tersecontext_tersecontext 2>/dev/null || true

# 2. Configure
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=<your key>
# Optional: set SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL

# 3. Start everything
docker compose up --build
```

Open http://localhost:5173 — login with the default admin user (`admin`).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `POSTGRES_PASSWORD` | `localpassword` | Postgres password |
| `TERSECONTEXT_URL` | `http://host.docker.internal:8090` | TerseContext API base URL |
| `SOURCE_DIRS` | `/repos` (in container) | Mounted from `~/workspaces` on host |
| `SLACK_BOT_TOKEN` | (optional) | Slack bot token (xoxb-...) |
| `SLACK_APP_TOKEN` | (optional) | Slack app token (xapp-...) |
| `SLACK_CHANNEL` | `tc-tasks` | Slack channel name for notifications |
| `DEFAULT_MODEL` | `claude-sonnet-4-20250514` | Claude model to use |

## SOURCE_DIRS

Your local workspaces directory (`~/workspaces`) is mounted read-only into the app container as `/repos`. TerseContext must have indexed the repos under that path. If your repos live elsewhere, edit the volume in `docker-compose.yml`:

```yaml
volumes:
  - /path/to/your/repos:/repos:ro
```

## TerseContext Setup

TerseContext must be running and its repos indexed before submitting tasks. The app connects to TerseContext via the `tersecontext_tersecontext` Docker network. The default URL assumes TerseContext is running on port 8090.

If TerseContext is not running, the app still starts but task research will fail. Create the network manually to allow Breakdown to start without TerseContext:

```bash
docker network create tersecontext_tersecontext 2>/dev/null || true
```

## Slack Setup

1. Create a Slack app with socket mode enabled
2. Required scopes: `channels:read`, `chat:write`, `app_mentions:read`
3. Install the app to your workspace
4. Set `SLACK_BOT_TOKEN` (xoxb-...) and `SLACK_APP_TOKEN` (xapp-...) in `.env`
5. Set `SLACK_CHANNEL` to the channel name where the bot should post

The bot is optional — if tokens are not set, the app runs without Slack integration.

## API Reference

### GET /api/tasks/{id}

Returns a single task with its research summary (if complete).

```json
{
  "id": "uuid",
  "title": "...",
  "status": "pending|researching|ready|approved|rejected",
  "summary": "...",
  "affected_files": ["..."],
  "created_at": "..."
}
```

## Redis Stream Consumer

Approved tasks are published to a Redis stream. To consume:

```bash
# List approved tasks
docker compose exec redis redis-cli XRANGE stream:breakdown-approved - +

# Read new entries since a given ID
docker compose exec redis redis-cli XREAD COUNT 10 STREAMS stream:breakdown-approved <last-id>
```

Each entry contains the full approval bundle: task metadata, research summary, affected files, and effort estimate.

## Local Development (without Docker)

```bash
cp .env.example .env
# Edit .env — use localhost URLs

pip install -e .
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README with Docker quick start and full configuration guide"
```

---

## Task 8: End-to-End Smoke Test

Verify the full stack starts and the happy path works.

- [ ] **Step 1: Build and start all services**

```bash
docker compose up --build
```

Watch the logs. Expected sequence:
1. `postgres` becomes healthy
2. `redis` becomes healthy
3. `app` runs `alembic upgrade head`, then starts FastAPI on 8000, then becomes healthy
4. `frontend` starts Vite dev server on 5173

If `app` exits immediately, check `docker compose logs app` — most likely cause is missing `ANTHROPIC_API_KEY` in `.env`.

- [ ] **Step 2: Verify API health**

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: Verify frontend loads**

Open http://localhost:5173 in a browser. Expected: login page appears. Log in as `admin`.

- [ ] **Step 4: Submit a task and verify research runs**

1. In the UI: select a repo, enter a feature request, submit
2. Watch `docker compose logs app` — should see LLM research starting
3. Wait for status to change to `ready`

- [ ] **Step 5: Approve and check Redis stream**

1. Approve the task in the UI
2. Check the stream:

```bash
docker compose exec redis redis-cli XRANGE stream:breakdown-approved - +
```

Expected: one entry with the approved bundle.

- [ ] **Step 6: Final commit if any fixups were needed**

```bash
git add -p   # stage only intentional changes
git commit -m "fix: <description of any smoke test fixups>"
```
