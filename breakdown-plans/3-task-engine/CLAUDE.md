# Subtask 3: Task API + research engine + Redis queue

**Layer:** 3 (sequential — depends on 2a, 2b, 2c all merged)
**Branch:** `feature/task-engine`
**Worktree:** `../breakdown-task-engine`

## Setup

```bash
cd breakdown
git worktree add -b feature/task-engine ../breakdown-task-engine
cp subtasks/3-task-engine/CLAUDE.md ../breakdown-task-engine/SUBTASK.md
cd ../breakdown-task-engine
```

## What to build

The core of the system. Task CRUD, the research engine that calls TC + LLM, and the Redis queue for approved tasks.

### Redis client

- Create `app/clients/redis.py`:
  - Class `RedisQueue` initialized with `redis_url: str`
  - `async def push_approved(self, bundle: dict)` — XADD to `stream:breakdown-approved` with the bundle as fields (JSON-serialize the complex fields)
  - `async def close(self)`

### Query builder

- Create `app/engine/query_builder.py`:
  - `def build_query(task: Task) -> str`
  - Combine task.description + relevant parts of task.optional_answers into a query string for TC
  - Keep under 500 chars — TC queries work best short and specific

### Research engine

- Create `app/engine/researcher.py`:
  - `async def research(task: Task, tc_client: TerseContextClient, llm_client: AnthropicClient) -> dict`
  - Steps:
    1. Build TC query from task via query_builder
    2. Query TerseContext → get code context string
    3. Store TC response in task.tc_context (update DB)
    4. Build LLM prompt:
       - System prompt: the research system prompt from root CLAUDE.md
       - User message: task description + optional_answers (if any) + TC context + additional_context entries
    5. Call LLM
    6. Parse JSON response
    7. Validate research output: has summary, affected_code (array), complexity (score 1-10, label, estimated_effort, reasoning), metrics (files_affected, files_created, files_modified, services_affected, contract_changes, new_dependencies, risk_areas)
    8. On JSON parse failure: retry once with "Your response was not valid JSON. Respond with only the JSON object."
    9. Return research dict

### Queue publisher

- Create `app/engine/queue.py`:
  - `async def publish_approved_task(task: Task, user: User, redis: RedisQueue)`
  - Build the bundle from root CLAUDE.md Redis queue section
  - Call `redis.push_approved(bundle)`

### Task routes

- Create `app/routes/tasks.py`:
  - `POST /api/tasks` — requires authenticated user. Creates task with submitter_id, state='submitted'. Kicks off research as background asyncio task. Returns task with state='submitted' immediately.
  - `GET /api/tasks` — list tasks, optional filter by state, repo, submitter. Returns list with id, feature_name, repo, state, submitter username, created_at.
  - `GET /api/tasks/{id}` — full task with research, tc_context, logs
  - `POST /api/tasks/{id}/approve` — admin only. Task must be in state='researched'. Sets state='approved', approved_by_id, pushes bundle to Redis queue. Logs approval.
  - `POST /api/tasks/{id}/reject` — admin only. Task must be in state='researched'. Sets state='rejected'. Accepts optional reason in body. Logs rejection.

### Background research flow

When `POST /api/tasks` creates a task:
1. Return 201 immediately with state='submitted'
2. In background (asyncio.create_task):
   a. Set state='researching', log
   b. Call `research()` from researcher.py
   c. Store research in task.research
   d. Set state='researched', log
   e. On failure: set state='failed', store error_message, log

### Task log entries

Log all state transitions to task_logs with: event name, actor_id (if user-initiated), detail (JSON with relevant context like error messages, research summary stats).

Events: `task_created`, `research_started`, `research_completed`, `research_failed`, `task_approved`, `task_rejected`, `task_queued`

### Register everything

- Register tasks router in `app/main.py`
- Initialize TerseContextClient, AnthropicClient, RedisQueue in lifespan
- Make them available to routes (app.state or dependency injection)

## Verify

```bash
# Start postgres + redis + TerseContext
uvicorn app.main:app --reload --port 8000

# Submit a task:
curl -X POST http://localhost:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -H 'X-User: kmcbeth' \
  -d '{
    "feature_name": "ts-parser",
    "description": "Add TypeScript support to the parser service. Handle .ts and .tsx files, extract functions/classes/methods/imports, produce ParsedFile events.",
    "repo": "tersecontext"
  }'
# expect: 201, state='submitted'

# Wait 10-15 seconds:
curl http://localhost:8000/api/tasks/{id} -H 'X-User: kmcbeth' | python -m json.tool
# expect: state='researched', research has summary, affected_code, complexity, metrics

# Approve (as admin):
curl -X POST http://localhost:8000/api/tasks/{id}/approve -H 'X-User: admin'
# expect: state='approved'

# Check Redis:
redis-cli XRANGE stream:breakdown-approved - +
# expect: the approved bundle

# Member cannot approve:
curl -X POST http://localhost:8000/api/tasks/{id}/approve -H 'X-User: kmcbeth'
# expect: 403

# Test failure (stop TerseContext, submit task):
# expect: state='failed', error_message populated
```

## Merge

```bash
cd ../breakdown
git merge feature/task-engine
git worktree remove ../breakdown-task-engine
```
