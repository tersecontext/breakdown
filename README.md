# Breakdown

Feature request submission and approval system for a small development team.

## What it does

1. A team member submits a feature request against a TerseContext-indexed repo
2. Breakdown queries TerseContext for relevant code context
3. Sends the feature + context to Claude → produces a research summary (affected files, complexity, effort estimate)
4. An admin reviews and approves or rejects
5. On approval, the full bundle is pushed to a Redis stream for downstream processing

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **Frontend**: React 18, Vite
- **Database**: PostgreSQL (port 5433)
- **Queue**: Redis (`stream:breakdown-approved`)
- **LLM**: Anthropic Claude (Sonnet)
- **Slack**: slack-bolt (socket mode)

## Setup

```bash
cp .env.example .env
# Edit .env with your credentials

pip install -e .

# Run migrations (after subtask 1)
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

## Configuration

See `.env.example` for all required environment variables.

- `DATABASE_URL` — PostgreSQL connection string (port 5433)
- `REDIS_URL` — Redis connection (shared with TerseContext)
- `TERSECONTEXT_URL` — TerseContext API base URL
- `SOURCE_DIRS` — comma-separated paths to indexed repos
- `ANTHROPIC_API_KEY` — Claude API key
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` — optional Slack integration
