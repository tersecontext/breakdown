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

## Components

### 1. `app/clients/redis.py` — RedisQueue

```python
class RedisQueue:
    def __init__(self, redis_url: str): ...
    async def push_approved(self, bundle: dict) -> None: ...
    async def close(self) -> None: ...
```

- Uses `redis.asyncio` (async Redis client)
- `push_approved` calls `XADD stream:breakdown-approved * <fields>`
- Redis streams require flat string key-value pairs — JSON-serialize any complex fields: `research`, `additional_context`, `optional_answers`
- Simple scalar fields (`task_id`, `feature_name`, `repo`, `branch_from`, `submitter`, `approved_by`, `approved_at`) are stored as-is

### 2. `app/engine/query_builder.py` — build_query

```python
def build_query(task: Task) -> str
```

- Combines `task.description` with relevant keys from `task.optional_answers` (scope notes, architecture notes, constraints)
- Keeps output under 500 chars — TC queries work best short and specific
- Returns only the query text string; the caller (`researcher.py`) is responsible for passing `task.repo` to `tc_client.query()`

### 3. `app/engine/researcher.py` — research

```python
async def research(
    task_id: UUID,
    tc_client: TerseContextClient,
    llm_client: AnthropicClient,
) -> None
```

**Key design decision:** Takes `task_id` (not a `Task` ORM object) and opens its own `AsyncSessionLocal()` session. This avoids ORM detachment errors — the request session is closed by the time the background coroutine runs.

Steps:
1. Open own DB session, load task by ID
2. Set `state='researching'`, log `research_started`
3. Build TC query via `query_builder.build_query(task)`
4. Call `tc_client.query(query_text, repo=task.repo)` → get context string
5. Store context in `task.tc_context`, flush to DB
6. Build LLM prompt:
   - `system`: the research system prompt (see Appendix)
   - `user message`: task description + optional_answers + tc_context + additional_context entries
7. Call `llm_client.chat(system, messages)`
8. Parse JSON response → validate against `ResearchOutput` schema
9. On JSON parse failure: retry once with a second `chat()` call — multi-turn, appending assistant's bad response + corrective user message: `"Your response was not valid JSON. Respond with only the JSON object."`
10. Store result in `task.research`, set `state='researched'`, log `research_completed`
11. On any failure: set `state='failed'`, store `error_message`, log `research_failed`
12. Close own session in `finally` block

### 4. `app/engine/queue.py` — publish_approved_task

```python
async def publish_approved_task(task: Task, user: User, redis: RedisQueue) -> None
```

Builds the bundle from the task and approving user, calls `redis.push_approved(bundle)`.

Bundle fields:
```
task_id, feature_name, description, repo, branch_from,
submitter (username), approved_by (username), approved_at (ISO string),
tc_context, research (JSON), additional_context (JSON), optional_answers (JSON)
```

### 5. `app/routes/tasks.py` — Task routes

#### `POST /api/tasks`
- Auth: any authenticated user (`get_current_user`)
- Creates task with `submitter_id=user.id`, `state='submitted'`
- Logs `task_created`
- Launches `asyncio.create_task(research(task.id, ...))` — detached from request
- Returns 201 with full `TaskOut` immediately

#### `GET /api/tasks`
- Auth: any authenticated user
- Query params: `?state=`, `?repo=`, `?submitter=` (username string)
- Returns list of `TaskListItem` (not full `TaskOut` — avoids loading large blobs)

#### `GET /api/tasks/{id}`
- Auth: any authenticated user
- Returns full `TaskOut` including `tc_context`, `research`, `logs`

#### `POST /api/tasks/{id}/approve`
- Auth: admin only (`require_admin`)
- Task must be in `state='researched'` — 409 otherwise
- Sets `state='approved'`, `approved_by_id=user.id`
- Logs `task_approved`
- Calls `publish_approved_task(...)` → pushes to Redis
- Logs `task_queued` only on successful Redis push
- If Redis push fails: task remains `approved` in DB but `task_queued` is not logged — caller gets a 500; the `approved` state is preserved so a retry is possible

#### `POST /api/tasks/{id}/reject`
- Auth: admin only
- Task must be in `state='researched'` — 409 otherwise
- Sets `state='rejected'`
- Logs `task_rejected` with `detail={reason: ...}` if reason provided
- Body: `TaskReject` with `reason: str | None = None`

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
    created_at: datetime
    model_config = {"from_attributes": True}
```

Used by `GET /api/tasks` — does not load `tc_context` or `research`.

### Updated: `TaskReject`

```python
class TaskReject(BaseModel):
    reason: str | None = None
```

### Updated: `TaskOut`

Add `logs` field:
```python
logs: list[TaskLogOut]
```

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

## Task log events

| Event | When | actor_id |
|---|---|---|
| `task_created` | POST /api/tasks | submitter |
| `research_started` | background task begins | None |
| `research_completed` | research succeeds | None |
| `research_failed` | research fails | None |
| `task_approved` | approve endpoint | admin |
| `task_queued` | Redis push succeeds | admin |
| `task_rejected` | reject endpoint | admin |

---

## Wiring into `app/main.py`

In `lifespan`:
- Initialize `TerseContextClient(settings.tersecontext_url)` → `app.state.tc_client`
- Initialize `AnthropicClient(settings.anthropic_api_key, settings.default_model)` → `app.state.llm_client`
- Initialize `RedisQueue(settings.redis_url)` → `app.state.redis`
- On shutdown: call `.close()` on all three

In routes, access via `request.app.state` (passed through as a dependency or directly).

Register `tasks_router` in `app.include_router(tasks_router)`.

---

## State machine

```
submitted → researching → researched → approved → (queued to Redis)
                ↓               ↓
             failed          rejected
```

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
