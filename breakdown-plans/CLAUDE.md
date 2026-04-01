# CLAUDE.md — Breakdown

## What this project is

Breakdown is a feature request submission and approval system for a small development team. A team member submits a feature request against a TerseContext-indexed codebase. The system queries TerseContext for relevant code context, sends both artifacts to an LLM, and produces a research summary — what code is involved, what needs to change, how complex it is. An admin reviews and approves. On approval, the full bundle gets pushed to a Redis queue for a downstream consumer to pick up and act on.

Breakdown does not decompose into subtasks. It does not execute code. It does not produce implementation plans. It researches and assesses a feature request, gates it behind approval, and queues it.

TerseContext is already running at http://localhost:8090 and serves codebase context via POST /query. All target repos must be indexed in TerseContext.

---

## The flow

1. Member submits a feature request (web UI or Slack) against a repo
2. System queries TerseContext → gets relevant code context
3. System sends feature description + TC context to the LLM
4. LLM produces a research summary with complexity metrics
5. Research summary is displayed for review
6. Admin approves or rejects
7. On approval → full bundle pushed to Redis stream `stream:breakdown-approved`
8. Everything persisted in Postgres

---

## Stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, asyncio
- Frontend: React 18, Vite, React Router
- Database: PostgreSQL (separate instance, port 5433, database: breakdown)
- Queue: Redis (shared with TerseContext stack)
- Slack: slack-bolt for Python (socket mode)
- LLM: Anthropic SDK (Claude Sonnet)

---

## Repo structure

```
breakdown/
  app/
    main.py              FastAPI app, lifespan, CORS
    db.py                async SQLAlchemy engine + session
    config.py            Pydantic Settings from env vars
    models.py            SQLAlchemy ORM models
    schemas.py           Pydantic request/response schemas
    auth.py              Role-based auth (admin vs member)
    routes/
      tasks.py           Submit, list, get, approve, reject
      repos.py           Repo listing + TC index status
      users.py           User management
    engine/
      researcher.py      Builds prompt, calls LLM, parses research output
      query_builder.py   Builds TerseContext /query payloads
      queue.py           Pushes approved bundles to Redis
    clients/
      tersecontext.py    HTTP client for TC /query endpoint
      anthropic.py       Claude API client wrapper
      redis.py           Redis client for queue operations
      slack_bot.py       Slack Bolt app + handlers
  frontend/
    package.json
    vite.config.ts
    src/
      App.tsx
      api.ts
      pages/
        Submit.tsx
        TaskList.tsx
        TaskDetail.tsx
        Login.tsx
      components/
        RepoSelector.tsx
        FeatureForm.tsx
        ResearchView.tsx
  alembic/
    env.py
    versions/
  tests/
  Dockerfile
  docker-compose.yml
  pyproject.toml
  .env.example
  README.md
```

---

## Database schema

Separate Postgres instance (port 5433, database: breakdown).

### users

```sql
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username    TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT 'member',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Role enum: `admin`, `member`

### tasks

```sql
CREATE TABLE tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_name        TEXT NOT NULL,
    description         TEXT NOT NULL,
    repo                TEXT NOT NULL,
    branch_from         TEXT NOT NULL DEFAULT 'main',
    state               TEXT NOT NULL DEFAULT 'submitted',
    submitter_id        UUID NOT NULL REFERENCES users(id),
    approved_by_id      UUID REFERENCES users(id),
    source_channel      TEXT,
    slack_channel_id    TEXT,
    slack_thread_ts     TEXT,
    additional_context  JSONB DEFAULT '[]',
    optional_answers    JSONB DEFAULT '{}',
    tc_context          TEXT,
    research            JSONB,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

State enum: `submitted`, `researching`, `researched`, `approved`, `rejected`, `failed`

### task_logs

```sql
CREATE TABLE task_logs (
    id          SERIAL PRIMARY KEY,
    task_id     UUID NOT NULL REFERENCES tasks(id),
    event       TEXT NOT NULL,
    actor_id    UUID REFERENCES users(id),
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Task states

```
submitted → researching → researched → approved → (queued to Redis)
                 ↓              ↓
              failed         rejected
```

---

## Research summary format

```json
{
    "summary": "Plain English overview of what this feature involves.",
    "affected_code": [
        {
            "file": "path/to/file.py",
            "change_type": "create | modify | delete",
            "description": "What changes and why"
        }
    ],
    "complexity": {
        "score": 4,
        "label": "low | medium | high",
        "estimated_effort": "1-2 days",
        "reasoning": "Why this complexity rating"
    },
    "metrics": {
        "files_affected": 5,
        "files_created": 2,
        "files_modified": 3,
        "services_affected": 1,
        "contract_changes": false,
        "new_dependencies": ["package-name"],
        "risk_areas": ["description of risk"]
    }
}
```

---

## Redis queue

Stream key: `stream:breakdown-approved`

On approval, push full bundle:
```json
{
    "task_id": "uuid",
    "feature_name": "...",
    "description": "...",
    "repo": "...",
    "branch_from": "...",
    "submitter": "username",
    "approved_by": "admin-username",
    "tc_context": "...",
    "research": { ... },
    "additional_context": [...],
    "optional_answers": {...},
    "approved_at": "..."
}
```

---

## API endpoints

### Auth
```
POST   /api/auth/login         Login by username → returns user with role
GET    /api/auth/me             Current user
```

### Tasks
```
POST   /api/tasks               Submit feature request (member or admin) → starts researching
GET    /api/tasks               List tasks (filter by state, repo, submitter)
GET    /api/tasks/{id}          Get task with research summary
POST   /api/tasks/{id}/approve  Admin only → pushes to Redis
POST   /api/tasks/{id}/reject   Admin only → with reason
```

### Repos
```
GET    /api/repos               List repos with TC index status
GET    /api/repos/{name}/branches   Git branches
```

### Users
```
GET    /api/users               List users (admin only)
POST   /api/users               Create user with role (admin only)
PATCH  /api/users/{id}          Update role (admin only)
```

---

## Submission form fields

Required: repository, feature name, description

Optional: branch from, additional context (file paths as pills), scope notes, architecture notes, constraints, testing notes

---

## Research system prompt

```
You are analyzing a feature request against a codebase. You have been given the feature description, optional context from the requester, and relevant code context retrieved from the codebase.

Produce a JSON object with:

- "summary": 2-3 sentence plain English overview of what this feature involves and how it relates to the existing code

- "affected_code": array of objects, each with:
  - "file": file path
  - "change_type": "create" | "modify" | "delete"
  - "description": what changes in this file and why

- "complexity": object with:
  - "score": integer 1-10 (1=trivial config change, 10=major architectural rework)
  - "label": "low" (1-3), "medium" (4-6), or "high" (7-10)
  - "estimated_effort": human-readable estimate (e.g. "2-4 hours", "1-2 days", "1 week+")
  - "reasoning": why this complexity rating — what makes it easy or hard

- "metrics": object with:
  - "files_affected": total count
  - "files_created": count of new files
  - "files_modified": count of modified files
  - "services_affected": count of distinct services touched
  - "contract_changes": boolean — does this change any API contracts, event schemas, or shared interfaces
  - "new_dependencies": array of new packages/libraries needed
  - "risk_areas": array of strings describing potential risks or tricky parts

Respond with ONLY the JSON object, no other text.
```

---

## Config (.env)

```
DATABASE_URL=postgresql+asyncpg://breakdown:localpassword@localhost:5433/breakdown
REDIS_URL=redis://localhost:6379
TERSECONTEXT_URL=http://localhost:8090
SOURCE_DIRS=/home/kmcbeth/workspaces
ANTHROPIC_API_KEY=sk-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_CHANNEL=tc-tasks
DEFAULT_MODEL=claude-sonnet-4-20250514
PORT=8000
```

---

## Locked decisions

- Breakdown researches and assesses. It does not decompose or execute.
- Approval is role-gated: only admins can approve.
- On approval, bundle pushed to Redis stream `stream:breakdown-approved`.
- Database: separate Postgres instance (port 5433).
- Queue: Redis shared with TerseContext stack.
- Auth: simple username-based roles for v1.
- All repos must be indexed in TerseContext.
