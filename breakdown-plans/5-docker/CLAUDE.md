# Subtask 5: Docker Compose + integration

**Layer:** 5 (sequential — depends on 4a and 4b merged)
**Branch:** `feature/docker`
**Worktree:** `../breakdown-docker`

## Setup

```bash
cd breakdown
git worktree add -b feature/docker ../breakdown-docker
cp subtasks/5-docker/CLAUDE.md ../breakdown-docker/SUBTASK.md
cd ../breakdown-docker
```

## What to build

Containerize everything and make it work as a single `docker compose up`.

### docker-compose.yml

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
      - ~/workspaces:/repos:ro
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - default
      - tersecontext_tersecontext  # connect to TC's network for Redis

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    depends_on:
      - app

volumes:
  pgdata:

networks:
  tersecontext_tersecontext:
    external: true
```

Note: The app connects to TerseContext's Redis and network. Adjust network name if TC's docker-compose uses a different project name.

### Frontend Dockerfile

- Create `frontend/Dockerfile`: node:20-slim, npm install, npm run dev (for dev) or npm run build + serve (for prod)

### Alembic on startup

- Update `app/main.py` lifespan: run `alembic upgrade head` on startup (subprocess or programmatic)

### Create .env from .env.example

- Populate with real values for local development

### Update README.md

- Quick start: `docker compose up --build`
- How to configure SOURCE_DIRS
- How to connect to TerseContext (must be running, repos must be indexed)
- How to set up Slack app
- API reference for `GET /api/tasks/{id}` and the Redis stream
- Consumer documentation: how to read from `stream:breakdown-approved`

## Verify

```bash
docker compose up --build

# Open localhost:5173 — login, submit, review
# Slack bot responds (if configured)
# Submit a task, wait for research
# Approve, check Redis:
docker compose exec redis redis-cli XRANGE stream:breakdown-approved - +
# expect: approved bundle
```

## Merge

```bash
cd ../breakdown
git merge feature/docker
git worktree remove ../breakdown-docker
```
