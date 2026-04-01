# Task Engine Design — Subtask 3

**Date:** 2026-03-31
**Branch:** `feature/task-engine`
**Depends on:** Subtasks 2a (TerseContext client), 2b (Anthropic client), 2c (Auth) — all merged

---

## Overview

The task engine is the core of Breakdown. It provides:

- A task CRUD API for submitting, listing, viewing, approving, and rejecting feature requests
- A background research engine that calls TerseContext and the LLM to produce a structured research summary
- A Redis queue publisher that pushes approved bundles to `stream:breakdown-approved`

The existing codebase already has: ORM models (`Task`, `User`, `TaskLog`), Pydantic schemas, `TerseContextClient`, `AnthropicClient`, and auth dependencies (`get_current_user`, `require_admin`).

---

## Schema changes

### New: `TaskListItem`

```python
class TaskListItem(BaseModel):
    id: uuid.UUID
    feature_name: str
    repo: str
    state: str
    submitter_id: uuid.UUID
    submitter_username: str
    created_at: datetime
    model_config = {"from_attributes": False}
```

Populated manually from join query rows (not from ORM objects) — see `GET /api/tasks`.

### Updated: `TaskReject`

`TaskReject` in `app/schemas.py` currently has `reason: str` (required). The tasks route is the first consumer of this schema — no existing callers. Replace with:

```python
class TaskReject(BaseModel):
    reason: str | None = None
```

Product intent: rejection reason is optional.

### Updated: `TaskOut`

Add `approved_at` and `logs` fields:

```python
approved_at: datetime | None
logs: list[TaskLogOut] = []
```

**Important:** Accessing `task.logs` on an ORM object not loaded with `selectinload` raises `MissingGreenlet` in async SQLAlchemy. All endpoints returning `TaskOut` must load logs via `selectinload(Task.logs)` — see each endpoint.

### New: `TaskLogOut`

```python
class TaskLogOut(BaseModel):
    id: int
    event: str
    actor_id: uuid.UUID | None
    detail: dict | None
    created_at: datetime
    model_config = {"from_attributes": True}
```

---

## ORM model change

Add `approved_at` column to `Task`:

```python
approved_at: Mapped[datetime | None] = mapped_column(
    sa.DateTime(timezone=True), nullable=True
)
```

Set `task.approved_at = datetime.now(timezone.utc)` in the approve endpoint. Use `datetime.now(timezone.utc)` (timezone-aware) throughout this subtask.

A new Alembic migration is required: `ALTER TABLE tasks ADD COLUMN approved_at TIMESTAMPTZ`.

---

## Components

### 1. `app/clients/redis.py` — RedisQueue

```python
class RedisQueue:
    def __init__(self, redis_url: str): ...
    async def push_approved(self, bundle: dict) -> None: ...
    async def close(self) -> None: ...
```

- Uses `redis.asyncio`
- `push_approved` calls `XADD stream:breakdown-approved * <fields>`
- Redis streams require flat string key-value pairs — JSON-serialize complex fields: `research`, `additional_context`, `optional_answers`
- Simple scalars (`task_id`, `feature_name`, `description`, `repo`, `branch_from`, `submitter`, `approved_by`, `approved_at`) stored as-is

### 2. `app/engine/query_builder.py` — build_query

```python
def build_query(task: Task) -> str
```

- Starts with `task.description`
- Appends the following keys from `task.optional_answers` if present (non-empty string values only):
  - `"scope_notes"`, `"architecture_notes"`, `"constraints"`, `"testing_notes"`
  - Format: `"\nScope: {value}"`, `"\nArchitecture: {value}"`, `"\nConstraints: {value}"`, `"\nTesting: {value}"`
- Hard-truncates the combined string to 500 characters
- Returns only the query text string
- The caller (`researcher.py`) passes `task.repo` separately to `tc_client.query(query_text, repo=task.repo)`

### 3. `app/engine/researcher.py` — research

```python
async def research(
    task_id: UUID,
    tc_client: TerseContextClient,
    llm_client: AnthropicClient,
) -> None
```

**Takes `task_id` (not a `Task` ORM object).** Opens its own `AsyncSessionLocal()` session so it is fully independent of the request session, which is closed before the background coroutine runs.

The `RESEARCH_SYSTEM_PROMPT` constant is defined in this module (see Appendix).

Steps:
1. Open own DB session
2. Load task by ID (`select(Task).where(Task.id == task_id)`)
3. Set `state='researching'`, append `TaskLog(event='research_started')`, commit
4. Build TC query via `query_builder.build_query(task)`
5. Call `tc_client.query(query_text, repo=task.repo)` → context string. On `TerseContextError`, store `error_message=str(e)` and fall to step 14.
6. Store context in `task.tc_context`, commit
7. Build LLM user message string:
   ```
   Feature: {task.feature_name}
   Description: {task.description}
   {optional_answers formatted as "Key: value" lines for non-empty values}
   {additional_context items prefixed with "Context: " if non-empty}

   Code context:
   {tc_context}
   ```
8. Call `llm_client.chat(system=RESEARCH_SYSTEM_PROMPT, messages=[{"role": "user", "content": user_message}])`
9. Attempt `json.loads(response.content)`
10. If JSON parse fails: make a second `chat()` call with a corrective single-element messages list. The corrective message embeds the prior bad output inline so the model has context — it does not rely on conversation history (since `AnthropicClient.chat()` is stateless and uses flat text, not true multi-turn):
    ```python
    corrective = (
        f"Your previous response was not valid JSON. "
        f"Here is what you returned:\n\n{response.content}\n\n"
        f"Respond with only the JSON object, no other text."
    )
    response = await llm_client.chat(
        system=RESEARCH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": corrective}],
    )
    parsed = json.loads(response.content)  # if this fails too, fall to step 14
    ```
11. Validate `parsed` via `ResearchOutput(**parsed)`. If Pydantic raises a `ValidationError`, store `error_message=str(e)` and fall to step 14 (leave `task.research` as `None` — a task with null research must not be approved).
12. Store `parsed` dict in `task.research`, set `state='researched'`, append `TaskLog(event='research_completed')`, commit
13. Return
14. On any failure: set `state='failed'`, set `error_message=str(e)` (if not already set), append `TaskLog(event='research_failed', detail={"error": error_message})`, commit
15. Close own session in `finally` block

### 4. `app/engine/queue.py` — publish_approved_task

```python
async def publish_approved_task(task: Task, user: User, redis: RedisQueue) -> None
```

`task.submitter` relationship must be loaded before calling (see approve endpoint).

Bundle fields:
```
task_id             str(task.id)
feature_name        task.feature_name
description         task.description
repo                task.repo
branch_from         task.branch_from
submitter           task.submitter.username
approved_by         user.username
approved_at         task.approved_at.isoformat()
tc_context          task.tc_context or ""
research            json.dumps(task.research)
additional_context  json.dumps(task.additional_context)
optional_answers    json.dumps(task.optional_answers)
```

### 5. `app/routes/tasks.py` — Task routes

Router prefix: no prefix at router level — each route uses the full `/api/tasks/...` path, consistent with existing `repos.py` and `users.py`.

All routes that need clients access them via `request.app.state` — declare `request: Request` (from `fastapi import Request`) as a route parameter.

#### `POST /api/tasks`
- Auth: `get_current_user`
- Creates task with `submitter_id=user.id`, `state='submitted'`
- Appends `TaskLog(event='task_created', actor_id=user.id)`, commit
- Reload task for response: `await session.execute(select(Task).where(Task.id == task.id).options(selectinload(Task.logs)))` and return the reloaded object
- Creates background task: `t = asyncio.create_task(research(task.id, request.app.state.tc_client, request.app.state.llm_client))`
- Stores reference to prevent GC: `request.app.state.background_tasks.add(t)` with done-callback: `t.add_done_callback(request.app.state.background_tasks.discard)`
- Returns 201 with `TaskOut`

#### `GET /api/tasks`
- Auth: `get_current_user`
- **Visibility policy:** shared team queue — all authenticated users can see all tasks. This is intentional for v1.
- Query params: `?state=` (str, optional), `?repo=` (str, optional), `?submitter=` (str — username, optional)
- Query:
  ```python
  stmt = select(Task, User.username).join(User, Task.submitter_id == User.id)
  if state: stmt = stmt.where(Task.state == state)
  if repo: stmt = stmt.where(Task.repo == repo)
  if submitter: stmt = stmt.where(User.username == submitter)
  rows = (await session.execute(stmt)).all()
  return [
      TaskListItem(
          id=task.id,
          feature_name=task.feature_name,
          repo=task.repo,
          state=task.state,
          submitter_id=task.submitter_id,
          submitter_username=username,
          created_at=task.created_at,
      )
      for task, username in rows
  ]
  ```

#### `GET /api/tasks/{id}`
- Auth: `get_current_user`
- Query: `select(Task).where(Task.id == id).options(selectinload(Task.logs))`
- 404 if not found
- Returns `TaskOut`

#### `POST /api/tasks/{id}/approve`
- Auth: `require_admin`
- Query: `select(Task).where(Task.id == id).options(selectinload(Task.submitter), selectinload(Task.logs))`
- 404 if not found
- 409 if `task.state != 'researched'`
- Set `state='approved'`, `approved_by_id=user.id`, `approved_at=datetime.now(timezone.utc)`
- Append `TaskLog(event='task_approved', actor_id=user.id)`
- **Single commit** for state change + log together — no window where state is `approved` but log is missing
- Call `publish_approved_task(task, user, request.app.state.redis)`
  - On success: append `TaskLog(event='task_queued', actor_id=user.id)`, commit; return `TaskOut`
  - On failure: `task_queued` log is not written; raise `HTTPException(500, "Redis publish failed")`. Task remains `approved` in DB — a retry of the approve endpoint will find state `!= 'researched'` and 409, so a manual state reset is required. Document this as a known v1 limitation.
- Returns `TaskOut`

#### `POST /api/tasks/{id}/reject`
- Auth: `require_admin`
- Query: `select(Task).where(Task.id == id).options(selectinload(Task.logs))`
- 404 if not found
- 409 if `task.state != 'researched'`
- Set `state='rejected'`
- Append `TaskLog(event='task_rejected', actor_id=user.id, detail={"reason": body.reason} if body.reason else None)`
- Commit
- Returns `TaskOut`

---

## Wiring into `app/main.py`

In `lifespan` startup:
```python
app.state.tc_client = TerseContextClient(settings.tersecontext_url)
app.state.llm_client = AnthropicClient(settings.anthropic_api_key, settings.default_model)
app.state.redis = RedisQueue(settings.redis_url)
app.state.background_tasks = set()  # holds references to prevent GC
```

In `lifespan` shutdown:
```python
await app.state.tc_client.close()
await app.state.redis.close()
# AnthropicClient has no close() method — claude_agent_sdk spawns per-invocation
# subprocesses that do not hold persistent handles; no cleanup needed.
```

Register: `app.include_router(tasks_router)`

---

## Task log events

| Event | When | actor_id |
|---|---|---|
| `task_created` | POST /api/tasks | submitter |
| `research_started` | background task begins | None |
| `research_completed` | research succeeds | None |
| `research_failed` | research fails | None |
| `task_approved` | approve endpoint (same commit as state change) | admin |
| `task_queued` | Redis push succeeds | admin |
| `task_rejected` | reject endpoint | admin |

---

## State machine

```
submitted → researching → researched → approved → (queued to Redis)
                ↓               ↓
             failed          rejected
```

Known v1 limitations:
- If the background task crashes before `state='researching'` is committed, the task stays in `submitted` indefinitely. Identify by `created_at` age.
- If the background task crashes while in `researching`, the task stays in `researching` indefinitely. Same recovery: manual DB update.
- If Redis publish fails after `state='approved'` is committed, the task is `approved` but not queued. The approve endpoint returns 500. A subsequent approve attempt gets 409 (state != `researched`). Recovery requires a manual `state` reset in the DB, then re-approving.

---

## Alembic migration

One new migration is required to add `approved_at TIMESTAMPTZ` (nullable) to the `tasks` table.

---

## Appendix: Research system prompt

```
You are analyzing a feature request against a codebase. You have been given the
feature description, optional context from the requester, and relevant code context
retrieved from the codebase.

Produce a JSON object with:

- "summary": 2-3 sentence plain English overview of what this feature involves
  and how it relates to the existing code

- "affected_code": array of objects, each with:
  - "file": file path
  - "change_type": "create" | "modify" | "delete"
  - "description": what changes in this file and why

- "complexity": object with:
  - "score": integer 1-10
  - "label": "low" (1-3), "medium" (4-6), or "high" (7-10)
  - "estimated_effort": human-readable estimate (e.g. "2-4 hours", "1-2 days")
  - "reasoning": why this complexity rating

- "metrics": object with:
  - "files_affected": total count
  - "files_created": count of new files
  - "files_modified": count of modified files
  - "services_affected": count of distinct services touched
  - "contract_changes": boolean
  - "new_dependencies": array of new packages/libraries needed
  - "risk_areas": array of strings describing potential risks

Respond with ONLY the JSON object, no other text.
```
