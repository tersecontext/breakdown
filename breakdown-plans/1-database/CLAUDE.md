# Subtask 1: Database + models

**Layer:** 1 (sequential — depends on subtask 0)
**Branch:** `feature/database`
**Worktree:** `../breakdown-database`

## Setup

```bash
cd breakdown
git worktree add -b feature/database ../breakdown-database
cp subtasks/1-database/CLAUDE.md ../breakdown-database/SUBTASK.md
cd ../breakdown-database
```

## What to build

Set up SQLAlchemy async models and Alembic migrations. The root CLAUDE.md has the exact SQL schemas — match them precisely.

- Create `app/db.py`:
  - `create_async_engine` from `config.database_url`
  - `async_sessionmaker` bound to engine
  - `async def get_session()` as a FastAPI dependency (yields session)
- Create `app/models.py`: SQLAlchemy 2.0 mapped classes:
  - `User`: id (UUID, server_default gen_random_uuid), username (unique), role (default 'member'), created_at
  - `Task`: id (UUID), feature_name, description, repo, branch_from, state (default 'submitted'), submitter_id (FK users), approved_by_id (FK users, nullable), source_channel, slack_channel_id, slack_thread_ts, additional_context (JSONB, default []), optional_answers (JSONB, default {}), tc_context (Text, nullable), research (JSONB, nullable), error_message (nullable), created_at, updated_at
  - `TaskLog`: id (serial), task_id (FK tasks), event, actor_id (FK users, nullable), detail (JSONB, nullable), created_at
  - Use `Mapped[]` type annotations throughout
- Initialize Alembic: `alembic init alembic`
- Configure `alembic/env.py`: async engine, import models metadata
- Generate migration: `alembic revision --autogenerate -m "initial tables"`
- Update `app/main.py`: add lifespan that creates engine, add placeholder `/health` endpoint

## Verify

```bash
# Start postgres on port 5433 (or docker run)
docker run -d --name breakdown-pg -e POSTGRES_DB=breakdown -e POSTGRES_USER=breakdown -e POSTGRES_PASSWORD=localpassword -p 5433:5432 postgres:16

alembic upgrade head
python -c "from app.models import User, Task, TaskLog; print('models ok')"
```

## Merge

```bash
cd ../breakdown
git merge feature/database
git worktree remove ../breakdown-database
docker stop breakdown-pg  # if started for testing
```
