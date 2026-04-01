# Subtask 6: Tests

**Layer:** 6 (sequential — depends on subtask 5 merged)
**Branch:** `feature/tests`
**Worktree:** `../breakdown-tests`

## Setup

```bash
cd breakdown
git worktree add -b feature/tests ../breakdown-tests
cp subtasks/6-tests/CLAUDE.md ../breakdown-tests/SUBTASK.md
cd ../breakdown-tests
```

## What to build

Unit and integration tests for critical paths. Add pytest + pytest-asyncio + httpx to dev dependencies.

### Test fixtures

- `tests/conftest.py`:
  - Test database: create a `breakdown_test` database, run migrations, yield session, drop after
  - FastAPI test client: httpx AsyncClient with `app` transport
  - Mock TerseContext: fixture that returns canned context strings
  - Mock Anthropic: fixture that returns canned research JSON

### Store / DB tests

- `tests/test_models.py`: create user, create task with FK to user, create task_log with FK to task. Verify relationships load correctly.

### Auth tests

- `tests/test_auth.py`:
  - Login creates user if not exists
  - Login returns existing user
  - X-User header resolves to correct user
  - Missing X-User returns 401
  - Admin check passes for admin role
  - Admin check rejects member role with 403

### Task API tests

- `tests/test_tasks.py`:
  - POST /api/tasks creates task with state='submitted'
  - GET /api/tasks lists tasks
  - GET /api/tasks filters by state and repo
  - GET /api/tasks/{id} returns full task
  - POST /api/tasks/{id}/approve requires admin, changes state to 'approved'
  - POST /api/tasks/{id}/approve with member returns 403
  - POST /api/tasks/{id}/approve on non-researched task returns 400
  - POST /api/tasks/{id}/reject requires admin, changes state to 'rejected'

### Repos API tests

- `tests/test_repos.py`:
  - GET /api/repos scans directories (mock SOURCE_DIRS to a temp dir with a git repo)
  - GET /api/repos/{name}/branches returns branch list
  - TC status populated when TC is reachable (mock)
  - TC status null when TC is down (mock)

### TC client tests

- `tests/test_tc_client.py`:
  - Successful query returns context string
  - Timeout after 10s raises TerseContextError
  - Retries on first failure, succeeds on second
  - Raises after 2 failed retries

### Research engine tests

- `tests/test_researcher.py`:
  - Valid research output passes validation
  - Missing fields in LLM response caught
  - Invalid complexity score caught
  - JSON parse failure triggers retry
  - TC context cached in task after query

### Redis queue tests

- `tests/test_queue.py`:
  - push_approved writes to stream:breakdown-approved
  - Bundle contains all required fields
  - (mock Redis or use testcontainers)

## Verify

```bash
pytest tests/ -v
# All pass
```

## Merge

```bash
cd ../breakdown
git merge feature/tests
git worktree remove ../breakdown-tests
```
