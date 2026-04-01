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
