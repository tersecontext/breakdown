# Subtask 0: Scaffold + config

**Layer:** 0 (sequential — must complete before anything else)
**Branch:** `feature/scaffold`
**Worktree:** `../breakdown-scaffold`

## Setup

```bash
cd breakdown
git worktree add -b feature/scaffold ../breakdown-scaffold
cp CLAUDE.md ../breakdown-scaffold/
cp subtasks/0-scaffold/CLAUDE.md ../breakdown-scaffold/SUBTASK.md
cd ../breakdown-scaffold
```

## What to build

Create the repo skeleton and install dependencies. Everything else depends on this.

- Create `pyproject.toml` with dependencies: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, httpx, anthropic, slack-bolt, redis
- Create `.env.example` with all config vars from root CLAUDE.md Config section
- Create the full directory structure from root CLAUDE.md Repo structure — empty `__init__.py` in all Python packages
- Create `app/config.py`: Pydantic `Settings` reading from `.env`:
  - `database_url: str`
  - `redis_url: str = "redis://localhost:6379"`
  - `tersecontext_url: str = "http://localhost:8090"`
  - `source_dirs: str` (comma-separated)
  - `anthropic_api_key: str`
  - `slack_bot_token: str = ""`
  - `slack_app_token: str = ""`
  - `slack_channel: str = "tc-tasks"`
  - `default_model: str = "claude-sonnet-4-20250514"`
  - `port: int = 8000`
- Create `app/schemas.py`: Pydantic models for all API shapes. Reference the root CLAUDE.md for task schema, research format, user schema.
- Create `Dockerfile`: python:3.12-slim, copy app, pip install, CMD uvicorn
- Create `README.md` with project overview

## Verify

```bash
pip install -e .
python -c "from app.config import Settings; print('ok')"
python -c "from app.schemas import TaskCreate, ResearchOutput, UserCreate; print('ok')"
```

## Merge

```bash
cd ../breakdown
git merge feature/scaffold
git worktree remove ../breakdown-scaffold
```
