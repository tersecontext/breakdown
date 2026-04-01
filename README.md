# Breakdown

Feature request submission and AI-assisted research system for development teams. Team members submit feature requests against a TerseContext-indexed repo; Claude analyzes the codebase and produces a structured research summary; an admin approves or rejects; approved tasks are published to a Redis stream for downstream automation.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker with Compose v2 | `docker compose version` should show v2.x |
| [TerseContext](https://github.com/tersecontext/tersecontext) | Must be running with at least one repo indexed. See TerseContext's `make up` / `make demo`. |
| Anthropic API key | Set as `ANTHROPIC_API_KEY` in `.env` |

Breakdown connects to TerseContext on the `tersecontext_tersecontext` Docker network. Start TerseContext first.

## How It Works

```
Submit (Web UI or Slack)
         │
         ▼
  TerseContext query ──► relevant code context
         │
         ▼
  Claude research ──► affected files, complexity, effort, risks
         │
         ▼
  Admin review (Web UI or Slack)
         │
    ┌────┴────┐
  Approve   Reject
    │
    ▼
Redis stream (stream:breakdown-approved)
    │
    ▼
Downstream systems (CI, build agents, etc.)
```

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Frontend | React 19, Vite, TypeScript, React Router 7 |
| Database | PostgreSQL 16 |
| Queue | Redis 7 (`stream:breakdown-approved`) |
| LLM | Anthropic Claude (Sonnet) via claude-agent-sdk |
| Notifications | Slack (socket mode, optional) |
| Code Context | TerseContext (external service) |

---

## Quick Start (Docker)

**Prerequisites:** Docker with Compose v2, TerseContext running with repos indexed.

```bash
# 1. Create the external Docker network (required even without TerseContext)
docker network create tersecontext_tersecontext 2>/dev/null || true

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set:
#   ANTHROPIC_API_KEY=sk-ant-...
#   SOURCE_DIRS=/repos  (or your repo path)

# 3. Start all services
docker compose up --build
```

Open **http://localhost:5173** and log in with username `admin`.

> **First login:** The app auto-creates an `admin` user on startup. No password — authentication is username-only.

---

## Configuration

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Claude API key (sk-ant-...) |
| `SECRET_KEY` | (required) | Secret for signing JWTs — min 32 chars |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...@localhost:5433/breakdown` | Full async DSN |
| `POSTGRES_PASSWORD` | `localpassword` | Postgres password (also used in DATABASE_URL) |

### Services

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `TERSECONTEXT_URL` | `http://host.docker.internal:8090` | TerseContext API base URL |
| `SOURCE_DIRS` | `/repos` | Comma-separated host paths to scan for git repos |

### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MODEL` | `claude-sonnet-4-20250514` | Claude model ID |

### Auth

| Variable | Default | Description |
|----------|---------|-------------|
| `ACCESS_TOKEN_TTL` | `900` | Access token lifetime in seconds (15 min) |
| `REFRESH_TOKEN_TTL` | `604800` | Refresh token lifetime in seconds (7 days) |
| `CORS_ORIGINS` | `[]` | Allowed CORS origins e.g. `["http://localhost:5173"]` |

### Slack (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_BOT_TOKEN` | — | Bot token (xoxb-...) |
| `SLACK_APP_TOKEN` | — | App-level token (xapp-...) |
| `SLACK_CHANNEL` | `tc-tasks` | Channel to monitor and post to |

Slack is fully optional. If tokens are not set, the app runs without it.

---

## Usage Guide

### Submitting a Feature Request

**Via Web UI:**
1. Open http://localhost:5173 and log in
2. Click **New Request**
3. Select the target repo and branch
4. Enter a feature name and description
5. Optionally expand the **Additional Context** section for:
   - Specific file paths affected
   - Scope constraints
   - Architecture preferences
   - Testing requirements
6. Click **Submit** — research starts automatically

**Via Slack:**
1. Post a message describing the feature in the configured Slack channel
2. The bot responds with repo selector buttons
3. Select the target repo
4. The bot posts a research summary with Approve/Reject buttons (visible to admins)

### Task States

```
submitted → researching → researched ──► approved
                    │              └──► rejected
                    ▼
                  failed
```

| State | Meaning |
|-------|---------|
| `submitted` | Task created, research queued |
| `researching` | Claude + TerseContext in progress |
| `researched` | Research complete, awaiting admin decision |
| `approved` | Admin approved, published to Redis stream |
| `rejected` | Admin rejected |
| `failed` | Research failed (error stored for debugging) |

### Reviewing and Approving

**Via Web UI:**
1. Open the task list — filter by state, repo, or submitter
2. Click a task to view the full research summary
3. Admins see **Approve** / **Reject** buttons on `researched` tasks

**Via Slack:**
- Research summaries are posted automatically with inline action buttons

### Managing Users

Users are managed via the API (admin only):

```bash
# Create a new user
curl -X POST http://localhost:8000/api/users \
  -H "X-User: admin" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "role": "member"}'

# Promote to admin
curl -X PATCH http://localhost:8000/api/users/<id> \
  -H "X-User: admin" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

---

## API Reference

All endpoints require the `X-User: <username>` header. Admin-only endpoints additionally require the user's role to be `admin`.

### Auth

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/login` | — | Login / auto-register |
| GET | `/api/auth/me` | User | Current user info |

### Users (Admin only)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/users` | Create user |
| GET | `/api/users` | List all users |
| PATCH | `/api/users/{id}` | Update role |

### Repos

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/repos` | User | List repos with TerseContext index status |
| GET | `/api/repos/{name}/branches` | User | List branches for a repo |

### Tasks

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/tasks` | User | Create task and trigger research |
| GET | `/api/tasks` | User | List tasks (query: `state`, `repo`, `submitter`) |
| GET | `/api/tasks/{id}` | User | Full task detail with logs |
| POST | `/api/tasks/{id}/approve` | Admin | Approve and publish to Redis |
| POST | `/api/tasks/{id}/reject` | Admin | Reject task |

### Task Object

```json
{
  "id": "uuid",
  "feature_name": "Add dark mode toggle",
  "description": "Users want a dark mode...",
  "repo": "my-app",
  "branch_from": "main",
  "state": "researched",
  "submitter": "alice",
  "approver": null,
  "approved_at": null,
  "error_message": null,
  "research": {
    "summary": "...",
    "affected_files": [
      {"path": "src/theme.ts", "change_type": "modify"}
    ],
    "complexity_score": 3,
    "effort_estimate": "2-4 hours",
    "risk_areas": ["CSS variable conflicts"],
    "new_dependencies": [],
    "metrics": {
      "files_affected": 4,
      "services_affected": 0,
      "contract_changes": false
    }
  },
  "logs": [
    {"event": "task_created", "actor": "alice", "timestamp": "..."},
    {"event": "research_completed", "actor": "system", "timestamp": "..."}
  ]
}
```

---

## Authentication

Breakdown uses username + password login. On first login, any password is accepted and stored (for existing users created before this feature). Subsequent logins require the stored password.

Login returns a short-lived JWT access token (15 min) and sets an HttpOnly refresh token cookie (7 days). The frontend stores the access token in memory and refreshes automatically.

To change a password after login, `POST /api/auth/set-password` with `{"new_password": "..."}` and a valid Bearer token.

---

## Redis Stream

Approved tasks are published to `stream:breakdown-approved`. Each entry contains the full approval bundle.

### Consuming the Stream

```bash
# View all approved tasks
docker compose exec redis redis-cli XRANGE stream:breakdown-approved - +

# Read new entries (consumer pattern)
docker compose exec redis redis-cli XREAD COUNT 10 STREAMS stream:breakdown-approved <last-id>

# Read from the beginning
docker compose exec redis redis-cli XREAD COUNT 10 STREAMS stream:breakdown-approved 0-0
```

### Stream Entry Payload

```json
{
  "task_id": "uuid",
  "feature_name": "...",
  "description": "...",
  "repo": "my-app",
  "branch_from": "main",
  "submitter": "alice",
  "approved_by": "admin",
  "approved_at": "2026-04-01T12:00:00Z",
  "tc_context": "...relevant code snippets...",
  "research": "{...serialized research JSON...}",
  "additional_context": "[\"src/theme.ts\"]",
  "optional_answers": "{}"
}
```

---

## TerseContext Setup

TerseContext must be running before submitting tasks. The app connects via the `tersecontext_tersecontext` Docker network.

- Default expected URL: `http://host.docker.internal:8090`
- Override via `TERSECONTEXT_URL` in `.env`
- The app **will start without TerseContext**, but research will fail on submission

To use a different TerseContext address (e.g., if running on the same Compose network):
```bash
# .env
TERSECONTEXT_URL=http://tersecontext:8090
```

---

## Slack Setup

1. Create a Slack app at https://api.slack.com/apps
2. Enable **Socket Mode** and generate an App-Level Token (xapp-...)
3. Add bot scopes: `channels:read`, `chat:write`, `app_mentions:read`, `users:read`
4. Subscribe to the `message.channels` bot event
5. Install the app to your workspace and copy the Bot Token (xoxb-...)
6. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`
7. Invite the bot to the channel: `/invite @your-bot-name`

---

## Local Development (without Docker)

**Backend:**
```bash
# Start Postgres and Redis (or use Docker for just these)
docker compose up postgres redis -d

cp .env.example .env
# Edit .env with local DATABASE_URL (localhost:5433)

pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# Proxies /api to http://localhost:8000
```

**Running Tests:**

**Before running tests**, migrate the test database:
```bash
DATABASE_URL=postgresql+asyncpg://tersecontext:localpassword@172.26.0.7/breakdown_test \
  alembic upgrade head
```

```bash
# Requires a running test database
pytest
pytest -x              # stop on first failure
pytest tests/test_tasks.py  # single file
```

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "describe change"

# Rollback one step
alembic downgrade -1
```
# breakdown
this project gives you code research with a feature request from a ui, and allows someone to approve this work. it generates a plan with complexity, breaking down your feature ask for what it thinks the cost would be.
