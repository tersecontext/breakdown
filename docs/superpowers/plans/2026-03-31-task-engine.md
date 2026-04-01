# Task Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the task submission, research, approval, and queueing system — the core of Breakdown.

**Architecture:** Background asyncio tasks handle LLM research independently of the request lifecycle, each opening their own DB session. Route handlers access shared clients (TerseContext, LLM, Redis) via `request.app.state`. All test cases use mocks — no real DB or external services required.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, asyncpg, redis.asyncio, Alembic, pytest-asyncio, httpx ASGITransport

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `app/models.py` | Modify | Add `approved_at` column to `Task` |
| `app/schemas.py` | Modify | Add `TaskListItem`, `TaskLogOut`; update `TaskOut`, `TaskReject` |
| `app/clients/redis.py` | Create | `RedisQueue` — XADD to Redis stream |
| `app/engine/query_builder.py` | Create | `build_query()` — builds TC query string from task |
| `app/engine/researcher.py` | Create | `research()` — TC + LLM background coroutine |
| `app/engine/queue.py` | Create | `publish_approved_task()` — builds and pushes bundle |
| `app/routes/tasks.py` | Create | 5 task endpoints |
| `app/main.py` | Modify | Wire clients into lifespan; register tasks router |
| `alembic/versions/<rev>_add_approved_at.py` | Create | Migration: add `approved_at TIMESTAMPTZ` to tasks |
| `tests/test_redis_client.py` | Create | Unit tests for RedisQueue |
| `tests/test_query_builder.py` | Create | Unit tests for build_query |
| `tests/test_researcher.py` | Create | Unit tests for research() with mocks |
| `tests/test_queue.py` | Create | Unit tests for publish_approved_task |
| `tests/test_tasks.py` | Create | Integration tests for task routes |

---

## Task 1: DB migration — add `approved_at`

**Files:**
- Modify: `app/models.py`
- Create: `alembic/versions/<rev>_add_approved_at.py`

- [ ] **Step 1: Add `approved_at` to the Task ORM model**

In `app/models.py`, add after the `approved_by_id` field:

```python
from datetime import datetime
import sqlalchemy as sa

# Inside class Task:
approved_at: Mapped[datetime | None] = mapped_column(
    sa.DateTime(timezone=True), nullable=True
)
```

- [ ] **Step 2: Generate the Alembic migration**

```bash
alembic revision --autogenerate -m "add_approved_at"
```

Open the generated file. Verify the `upgrade()` function contains:
```python
op.add_column('tasks', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
```

If autogenerate adds anything else unexpected, remove it.

- [ ] **Step 3: Run the migration**

Requires a running Postgres instance (port 5433, database: breakdown).

```bash
alembic upgrade head
```

Expected: `Running upgrade c927b8850f78 -> <new_rev>, add_approved_at`

- [ ] **Step 4: Commit**

```bash
git add app/models.py alembic/versions/
git commit -m "feat: add approved_at column to tasks"
```

---

## Task 2: Schema updates

**Files:**
- Modify: `app/schemas.py`

No tests needed — these are pure data structures verified by the type checker and used by later tests.

- [ ] **Step 1: Add `TaskLogOut` schema**

In `app/schemas.py`, after the `ResearchOutput` block:

```python
class TaskLogOut(BaseModel):
    id: int
    event: str
    actor_id: uuid.UUID | None
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Add `TaskListItem` schema**

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

- [ ] **Step 3: Update `TaskOut`**

Add `approved_at` and `logs` to the existing `TaskOut` class:

```python
class TaskOut(BaseModel):
    id: uuid.UUID
    feature_name: str
    description: str
    repo: str
    branch_from: str
    state: str
    submitter_id: uuid.UUID
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None          # new
    source_channel: str | None
    slack_channel_id: str | None
    slack_thread_ts: str | None
    additional_context: list[Any]
    optional_answers: dict[str, Any]
    tc_context: str | None
    research: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    logs: list[TaskLogOut] = []           # new

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Update `TaskReject`**

Replace the existing `TaskReject`:

```python
class TaskReject(BaseModel):
    reason: str | None = None
```

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py
git commit -m "feat: add TaskListItem, TaskLogOut schemas; update TaskOut and TaskReject"
```

---

## Task 3: RedisQueue client

**Files:**
- Create: `app/clients/redis.py`
- Create: `tests/test_redis_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_redis_client.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_push_approved_xadds_to_stream():
    """push_approved() calls XADD on stream:breakdown-approved with bundle fields"""
    mock_redis = AsyncMock()

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        await q.push_approved({
            "task_id": "abc-123",
            "feature_name": "my-feature",
            "research": {"summary": "test"},
            "additional_context": ["file.py"],
            "optional_answers": {"scope_notes": "narrow"},
        })

    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "stream:breakdown-approved"
    fields = call_args[0][1]
    assert fields["task_id"] == "abc-123"
    assert fields["feature_name"] == "my-feature"
    # Complex fields are JSON-serialized
    assert fields["research"] == json.dumps({"summary": "test"})
    assert fields["additional_context"] == json.dumps(["file.py"])
    assert fields["optional_answers"] == json.dumps({"scope_notes": "narrow"})


@pytest.mark.asyncio
async def test_close_calls_aclose():
    """close() calls aclose() on the underlying Redis connection"""
    mock_redis = AsyncMock()

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        await q.close()

    mock_redis.aclose.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_redis_client.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `app.clients.redis` does not exist yet.

- [ ] **Step 3: Implement `app/clients/redis.py`**

```python
import json

import redis.asyncio as aioredis

COMPLEX_FIELDS = {"research", "additional_context", "optional_answers"}


class RedisQueue:
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)

    async def push_approved(self, bundle: dict) -> None:
        fields = {
            k: json.dumps(v) if k in COMPLEX_FIELDS else v
            for k, v in bundle.items()
        }
        await self._redis.xadd("stream:breakdown-approved", fields)

    async def close(self) -> None:
        await self._redis.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_redis_client.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/clients/redis.py tests/test_redis_client.py
git commit -m "feat: add RedisQueue client"
```

---

## Task 4: query_builder

**Files:**
- Create: `app/engine/query_builder.py`
- Create: `tests/test_query_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_query_builder.py`:

```python
from unittest.mock import MagicMock


def make_task(description, optional_answers=None):
    task = MagicMock()
    task.description = description
    task.optional_answers = optional_answers or {}
    return task


def test_build_query_returns_description_when_no_optional_answers():
    """build_query returns just the description when optional_answers is empty"""
    from app.engine.query_builder import build_query
    task = make_task("Add TypeScript support to the parser")
    result = build_query(task)
    assert result == "Add TypeScript support to the parser"


def test_build_query_appends_known_optional_answer_keys():
    """build_query appends scope_notes, architecture_notes, constraints, testing_notes"""
    from app.engine.query_builder import build_query
    task = make_task(
        "Add TypeScript support",
        optional_answers={
            "scope_notes": "only the parser service",
            "architecture_notes": "use visitor pattern",
            "constraints": "no new dependencies",
            "testing_notes": "unit tests only",
        },
    )
    result = build_query(task)
    assert "Scope: only the parser service" in result
    assert "Architecture: use visitor pattern" in result
    assert "Constraints: no new dependencies" in result
    assert "Testing: unit tests only" in result


def test_build_query_ignores_empty_optional_answer_values():
    """build_query skips optional_answers keys with empty string values"""
    from app.engine.query_builder import build_query
    task = make_task("Add TypeScript support", optional_answers={"scope_notes": ""})
    result = build_query(task)
    assert "Scope:" not in result


def test_build_query_ignores_unknown_optional_answer_keys():
    """build_query ignores keys not in the known set"""
    from app.engine.query_builder import build_query
    task = make_task("Add TypeScript support", optional_answers={"unknown_key": "value"})
    result = build_query(task)
    assert "unknown_key" not in result
    assert "value" not in result


def test_build_query_truncates_to_500_chars():
    """build_query hard-truncates output to 500 characters"""
    from app.engine.query_builder import build_query
    task = make_task("x" * 600)
    result = build_query(task)
    assert len(result) == 500


def test_build_query_does_not_truncate_when_under_500():
    """build_query returns full string when under 500 characters"""
    from app.engine.query_builder import build_query
    task = make_task("short description")
    result = build_query(task)
    assert result == "short description"
    assert len(result) < 500
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_query_builder.py -v
```

Expected: all fail with `ImportError`

- [ ] **Step 3: Implement `app/engine/query_builder.py`**

```python
from app.models import Task

_OPTIONAL_KEYS = [
    ("scope_notes", "Scope"),
    ("architecture_notes", "Architecture"),
    ("constraints", "Constraints"),
    ("testing_notes", "Testing"),
]

MAX_QUERY_LENGTH = 500


def build_query(task: Task) -> str:
    parts = [task.description]
    for key, label in _OPTIONAL_KEYS:
        value = task.optional_answers.get(key, "")
        if value and isinstance(value, str):
            parts.append(f"\n{label}: {value}")
    return "".join(parts)[:MAX_QUERY_LENGTH]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_query_builder.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/query_builder.py tests/test_query_builder.py
git commit -m "feat: add query_builder"
```

---

## Task 5: researcher

**Files:**
- Create: `app/engine/researcher.py`
- Create: `tests/test_researcher.py`

The `research()` function opens its own `AsyncSessionLocal` session. Tests patch `AsyncSessionLocal` to inject a mock session so no real DB is needed.

- [ ] **Step 1: Write failing tests**

Create `tests/test_researcher.py`:

```python
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


VALID_RESEARCH = {
    "summary": "This adds TypeScript parsing.",
    "affected_code": [{"file": "parser.py", "change_type": "modify", "description": "add ts handling"}],
    "complexity": {"score": 3, "label": "low", "estimated_effort": "2-4 hours", "reasoning": "small change"},
    "metrics": {
        "files_affected": 1, "files_created": 0, "files_modified": 1,
        "services_affected": 1, "contract_changes": False,
        "new_dependencies": [], "risk_areas": []
    }
}


def make_mock_task(task_id=None):
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.feature_name = "ts-parser"
    task.description = "Add TypeScript support"
    task.repo = "tersecontext"
    task.optional_answers = {}
    task.additional_context = []
    task.tc_context = None
    task.research = None
    task.state = "submitted"
    task.logs = []
    return task


def make_mock_session(task):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    session.execute.return_value = result
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_research_happy_path_sets_researched_state():
    """research() sets state='researched' and stores research dict on success"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "some code context"

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(VALID_RESEARCH)
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = mock_llm_response

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "researched"
    assert task.research == VALID_RESEARCH
    assert task.tc_context == "some code context"


@pytest.mark.asyncio
async def test_research_passes_repo_to_tc_client():
    """research() passes task.repo to tc_client.query()"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(VALID_RESEARCH)
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = mock_llm_response

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    mock_tc.query.assert_called_once()
    _, kwargs = mock_tc.query.call_args
    assert kwargs.get("repo") == "tersecontext"


@pytest.mark.asyncio
async def test_research_retries_on_json_parse_failure():
    """research() retries LLM call once if the first response is not valid JSON"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    bad_response = MagicMock()
    bad_response.content = "not valid json at all"
    good_response = MagicMock()
    good_response.content = json.dumps(VALID_RESEARCH)

    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = [bad_response, good_response]

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert mock_llm.chat.call_count == 2
    assert task.state == "researched"


@pytest.mark.asyncio
async def test_research_sets_failed_on_tc_error():
    """research() sets state='failed' when TerseContext raises"""
    from app.clients.tersecontext import TerseContextError
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.side_effect = TerseContextError("TC down")

    mock_llm = AsyncMock()

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "failed"
    assert "TC down" in task.error_message


@pytest.mark.asyncio
async def test_research_sets_failed_when_both_json_attempts_fail():
    """research() sets state='failed' when both LLM calls return non-JSON"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    bad_response = MagicMock()
    bad_response.content = "not json"
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = bad_response

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "failed"
    assert task.error_message is not None


@pytest.mark.asyncio
async def test_research_sets_failed_on_pydantic_validation_error():
    """research() sets state='failed' when LLM returns JSON but with wrong structure"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    # Valid JSON but missing required fields
    bad_research = MagicMock()
    bad_research.content = json.dumps({"summary": "ok"})  # missing affected_code etc.
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = bad_research

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "failed"
    assert task.research is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_researcher.py -v
```

Expected: all fail with `ImportError`

- [ ] **Step 3: Implement `app/engine/researcher.py`**

```python
import json
import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from app.clients.anthropic import AnthropicClient
from app.clients.tersecontext import TerseContextClient
from app.db import AsyncSessionLocal
from app.engine.query_builder import build_query
from app.models import Task, TaskLog
from app.schemas import ResearchOutput

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are analyzing a feature request against a codebase. You have been given the feature description, optional context from the requester, and relevant code context retrieved from the codebase.

Produce a JSON object with:

- "summary": 2-3 sentence plain English overview of what this feature involves and how it relates to the existing code

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

Respond with ONLY the JSON object, no other text."""


async def research(
    task_id: UUID,
    tc_client: TerseContextClient,
    llm_client: AnthropicClient,
) -> None:
    async with AsyncSessionLocal() as session:
        task = None
        error_message = None
        try:
            result = await session.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task is None:
                logger.error("research: task %s not found", task_id)
                return

            task.state = "researching"
            session.add(TaskLog(task_id=task.id, event="research_started"))
            await session.commit()

            query_text = build_query(task)
            tc_context = await tc_client.query(query_text, repo=task.repo)
            task.tc_context = tc_context
            await session.commit()

            optional_parts = []
            for k, v in (task.optional_answers or {}).items():
                if v and isinstance(v, str):
                    optional_parts.append(f"{k}: {v}")

            context_parts = [f"Context: {c}" for c in (task.additional_context or [])]

            user_message = "\n".join(filter(None, [
                f"Feature: {task.feature_name}",
                f"Description: {task.description}",
                "\n".join(optional_parts),
                "\n".join(context_parts),
                "",
                "Code context:",
                tc_context,
            ]))

            response = await llm_client.chat(
                system=RESEARCH_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            try:
                parsed = json.loads(response.content)
            except json.JSONDecodeError:
                corrective = (
                    f"Your previous response was not valid JSON. "
                    f"Here is what you returned:\n\n{response.content}\n\n"
                    f"Respond with only the JSON object, no other text."
                )
                response = await llm_client.chat(
                    system=RESEARCH_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": corrective}],
                )
                parsed = json.loads(response.content)

            ResearchOutput(**parsed)  # validate structure; raises ValidationError if invalid

            task.research = parsed
            task.state = "researched"
            session.add(TaskLog(task_id=task.id, event="research_completed"))
            await session.commit()

        except Exception as e:
            error_message = str(e)
            logger.exception("research failed for task %s", task_id)
            if task is not None:
                task.state = "failed"
                task.error_message = error_message
                session.add(TaskLog(
                    task_id=task.id,
                    event="research_failed",
                    detail={"error": error_message},
                ))
                await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_researcher.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/researcher.py tests/test_researcher.py
git commit -m "feat: add research engine"
```

---

## Task 6: Queue publisher

**Files:**
- Create: `app/engine/queue.py`
- Create: `tests/test_queue.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_queue.py`:

```python
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone


def make_task():
    task = MagicMock()
    task.id = uuid.uuid4()
    task.feature_name = "ts-parser"
    task.description = "Add TypeScript support"
    task.repo = "tersecontext"
    task.branch_from = "main"
    task.tc_context = "some context"
    task.research = {"summary": "test research"}
    task.additional_context = ["file.py"]
    task.optional_answers = {"scope_notes": "narrow"}
    task.approved_at = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
    task.submitter = MagicMock()
    task.submitter.username = "kmcbeth"
    return task


def make_admin():
    admin = MagicMock()
    admin.username = "admin"
    return admin


@pytest.mark.asyncio
async def test_publish_approved_task_calls_push_approved():
    """publish_approved_task() calls redis.push_approved with the correct bundle"""
    from app.engine.queue import publish_approved_task

    task = make_task()
    admin = make_admin()
    mock_redis = AsyncMock()

    await publish_approved_task(task, admin, mock_redis)

    mock_redis.push_approved.assert_called_once()
    bundle = mock_redis.push_approved.call_args[0][0]

    assert bundle["task_id"] == str(task.id)
    assert bundle["feature_name"] == "ts-parser"
    assert bundle["description"] == "Add TypeScript support"
    assert bundle["repo"] == "tersecontext"
    assert bundle["branch_from"] == "main"
    assert bundle["submitter"] == "kmcbeth"
    assert bundle["approved_by"] == "admin"
    assert bundle["approved_at"] == "2026-03-31T12:00:00+00:00"
    assert bundle["tc_context"] == "some context"
    assert bundle["research"] == {"summary": "test research"}
    assert bundle["additional_context"] == ["file.py"]
    assert bundle["optional_answers"] == {"scope_notes": "narrow"}


@pytest.mark.asyncio
async def test_publish_approved_task_uses_empty_string_when_tc_context_is_none():
    """publish_approved_task() sends empty string for tc_context when it is None"""
    from app.engine.queue import publish_approved_task

    task = make_task()
    task.tc_context = None
    admin = make_admin()
    mock_redis = AsyncMock()

    await publish_approved_task(task, admin, mock_redis)

    bundle = mock_redis.push_approved.call_args[0][0]
    assert bundle["tc_context"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_queue.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `app/engine/queue.py`**

```python
from app.clients.redis import RedisQueue
from app.models import Task, User


async def publish_approved_task(task: Task, user: User, redis: RedisQueue) -> None:
    bundle = {
        "task_id": str(task.id),
        "feature_name": task.feature_name,
        "description": task.description,
        "repo": task.repo,
        "branch_from": task.branch_from,
        "submitter": task.submitter.username,
        "approved_by": user.username,
        "approved_at": task.approved_at.isoformat(),
        "tc_context": task.tc_context or "",
        "research": task.research,
        "additional_context": task.additional_context,
        "optional_answers": task.optional_answers,
    }
    await redis.push_approved(bundle)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_queue.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/queue.py tests/test_queue.py
git commit -m "feat: add queue publisher"
```

---

## Task 7: Task routes

**Files:**
- Create: `app/routes/tasks.py`
- Create: `tests/test_tasks.py`

Routes use `request.app.state` for clients and override `get_session` and auth deps via `app.dependency_overrides` in tests.

- [ ] **Step 1: Write failing tests**

Create `tests/test_tasks.py`:

```python
import asyncio
import json
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.auth import get_current_user, require_admin
from app.db import get_session
from app.models import User, Task, TaskLog


TASK_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()

member = User(id=USER_ID, username="kmcbeth", role="member")
admin_user = User(id=ADMIN_ID, username="admin", role="admin")


def make_task(state="submitted", research=None):
    task = MagicMock(spec=Task)
    task.id = TASK_ID
    task.feature_name = "ts-parser"
    task.description = "Add TypeScript support"
    task.repo = "tersecontext"
    task.branch_from = "main"
    task.state = state
    task.submitter_id = USER_ID
    task.approved_by_id = None
    task.approved_at = None
    task.source_channel = None
    task.slack_channel_id = None
    task.slack_thread_ts = None
    task.additional_context = []
    task.optional_answers = {}
    task.tc_context = None
    task.research = research
    task.error_message = None
    task.created_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    task.updated_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    task.logs = []
    task.submitter = member
    return task


def make_mock_session(task=None, user=None):
    session = AsyncMock()
    # Default execute returns task or user depending on what the test needs
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    result.scalars.return_value.all.return_value = [task] if task else []
    session.execute.return_value = result
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def setup_auth(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user


def setup_session(session):
    async def override():
        yield session
    app.dependency_overrides[get_session] = override


@pytest.mark.asyncio
async def test_post_tasks_creates_task_and_returns_201():
    """POST /api/tasks creates a task with state=submitted and returns 201"""
    task = make_task()
    session = make_mock_session(task)
    setup_auth(member)
    setup_session(session)

    with patch("app.routes.tasks.asyncio.create_task"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/tasks",
                json={"feature_name": "ts-parser", "description": "Add TypeScript support", "repo": "tersecontext"},
                headers={"X-User": "kmcbeth"},
            )

    assert response.status_code == 201
    data = response.json()
    assert data["feature_name"] == "ts-parser"
    assert data["state"] == "submitted"


@pytest.mark.asyncio
async def test_get_tasks_returns_list():
    """GET /api/tasks returns a list of TaskListItem"""
    session = AsyncMock()
    # Simulate join result returning (Task, username) rows
    row = MagicMock()
    row.__iter__ = MagicMock(return_value=iter([make_task(), "kmcbeth"]))
    result = MagicMock()
    result.all.return_value = [(make_task(), "kmcbeth")]
    session.execute.return_value = result
    setup_auth(member)

    async def override():
        yield session
    app.dependency_overrides[get_session] = override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/tasks", headers={"X-User": "kmcbeth"})

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["feature_name"] == "ts-parser"
    assert data[0]["submitter_username"] == "kmcbeth"


@pytest.mark.asyncio
async def test_get_task_by_id_returns_full_task():
    """GET /api/tasks/{id} returns full TaskOut"""
    task = make_task()
    session = make_mock_session(task)
    setup_auth(member)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/tasks/{TASK_ID}", headers={"X-User": "kmcbeth"})

    assert response.status_code == 200
    assert response.json()["id"] == str(TASK_ID)


@pytest.mark.asyncio
async def test_get_task_by_id_returns_404_when_not_found():
    """GET /api/tasks/{id} returns 404 when task does not exist"""
    session = make_mock_session(None)
    setup_auth(member)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/tasks/{uuid.uuid4()}", headers={"X-User": "kmcbeth"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_task_sets_approved_state():
    """POST /api/tasks/{id}/approve sets state=approved and pushes to Redis"""
    task = make_task(state="researched", research={"summary": "test"})
    task.approved_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    mock_redis = AsyncMock()
    app.state.redis = mock_redis
    app.state.tc_client = AsyncMock()
    app.state.llm_client = AsyncMock()
    app.state.background_tasks = set()

    with patch("app.routes.tasks.publish_approved_task", new_callable=AsyncMock) as mock_publish:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/tasks/{TASK_ID}/approve",
                headers={"X-User": "admin"},
            )

    assert response.status_code == 200
    assert task.state == "approved"
    mock_publish.assert_called_once()


@pytest.mark.asyncio
async def test_approve_task_returns_409_when_not_researched():
    """POST /api/tasks/{id}/approve returns 409 when task is not in state=researched"""
    task = make_task(state="submitted")
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/approve",
            headers={"X-User": "admin"},
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_task_returns_403_for_member():
    """POST /api/tasks/{id}/approve returns 403 when called by a non-admin"""
    app.dependency_overrides[get_current_user] = lambda: member
    app.dependency_overrides[require_admin] = lambda: (_ for _ in ()).throw(
        __import__('fastapi').HTTPException(status_code=403, detail="Admin required")
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/approve",
            headers={"X-User": "kmcbeth"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_task_sets_rejected_state():
    """POST /api/tasks/{id}/reject sets state=rejected"""
    task = make_task(state="researched")
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/reject",
            json={"reason": "not a priority"},
            headers={"X-User": "admin"},
        )

    assert response.status_code == 200
    assert task.state == "rejected"


@pytest.mark.asyncio
async def test_reject_task_returns_409_when_not_researched():
    """POST /api/tasks/{id}/reject returns 409 when task is not in state=researched"""
    task = make_task(state="approved")
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/reject",
            headers={"X-User": "admin"},
        )

    assert response.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tasks.py -v
```

Expected: most fail with `ImportError` or 404 (no router registered yet)

- [ ] **Step 3: Implement `app/routes/tasks.py`**

```python
import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_admin
from app.db import get_session
from app.engine.queue import publish_approved_task
from app.engine.researcher import research
from app.models import Task, TaskLog, User
from app.schemas import TaskCreate, TaskListItem, TaskOut, TaskReject

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/tasks", status_code=201, response_model=TaskOut)
async def create_task(
    body: TaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    task = Task(
        feature_name=body.feature_name,
        description=body.description,
        repo=body.repo,
        branch_from=body.branch_from,
        additional_context=body.additional_context,
        optional_answers=body.optional_answers,
        submitter_id=user.id,
        state="submitted",
    )
    session.add(task)
    session.add(TaskLog(task_id=task.id, event="task_created", actor_id=user.id))
    await session.commit()

    result = await session.execute(
        select(Task).where(Task.id == task.id).options(selectinload(Task.logs))
    )
    task = result.scalar_one()

    t = asyncio.create_task(
        research(task.id, request.app.state.tc_client, request.app.state.llm_client)
    )
    request.app.state.background_tasks.add(t)
    t.add_done_callback(request.app.state.background_tasks.discard)

    return task


@router.get("/api/tasks", response_model=list[TaskListItem])
async def list_tasks(
    state: str | None = None,
    repo: str | None = None,
    submitter: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Task, User.username).join(User, Task.submitter_id == User.id)
    if state:
        stmt = stmt.where(Task.state == state)
    if repo:
        stmt = stmt.where(Task.repo == repo)
    if submitter:
        stmt = stmt.where(User.username == submitter)

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


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Task).where(Task.id == task_id).options(selectinload(Task.logs))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/api/tasks/{task_id}/approve", response_model=TaskOut)
async def approve_task(
    task_id: UUID,
    request: Request,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.submitter), selectinload(Task.logs))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "researched":
        raise HTTPException(status_code=409, detail=f"Task is in state '{task.state}', expected 'researched'")

    task.state = "approved"
    task.approved_by_id = user.id
    task.approved_at = datetime.now(timezone.utc)
    session.add(TaskLog(task_id=task.id, event="task_approved", actor_id=user.id))
    await session.commit()

    try:
        await publish_approved_task(task, user, request.app.state.redis)
    except Exception as e:
        logger.error("Redis publish failed for task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Redis publish failed")

    session.add(TaskLog(task_id=task.id, event="task_queued", actor_id=user.id))
    await session.commit()

    result = await session.execute(
        select(Task).where(Task.id == task_id).options(selectinload(Task.logs))
    )
    return result.scalar_one()


@router.post("/api/tasks/{task_id}/reject", response_model=TaskOut)
async def reject_task(
    task_id: UUID,
    body: TaskReject = TaskReject(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Task).where(Task.id == task_id).options(selectinload(Task.logs))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "researched":
        raise HTTPException(status_code=409, detail=f"Task is in state '{task.state}', expected 'researched'")

    task.state = "rejected"
    detail = {"reason": body.reason} if body.reason else None
    session.add(TaskLog(task_id=task.id, event="task_rejected", actor_id=user.id, detail=detail))
    await session.commit()
    return task
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tasks.py -v
```

Expected: all pass. If a test fails due to mock setup, inspect the failure — do not skip it.

- [ ] **Step 5: Commit**

```bash
git add app/routes/tasks.py tests/test_tasks.py
git commit -m "feat: add task routes"
```

---

## Task 8: Wire `app/main.py`

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Update lifespan to initialize clients and register router**

Replace `app/main.py` with:

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.clients.anthropic import AnthropicClient
from app.clients.redis import RedisQueue
from app.clients.tersecontext import TerseContextClient
from app.config import settings
from app.db import AsyncSessionLocal, engine
from app.models import User
from app.routes.repos import router as repos_router
from app.routes.tasks import router as tasks_router
from app.routes.users import router as users_router


async def seed_admin() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        if result.first() is None:
            username = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
            session.add(User(username=username, role="admin"))
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_admin()
    app.state.tc_client = TerseContextClient(settings.tersecontext_url)
    app.state.llm_client = AnthropicClient(settings.anthropic_api_key, settings.default_model)
    app.state.redis = RedisQueue(settings.redis_url)
    app.state.background_tasks = set()
    yield
    await app.state.tc_client.close()
    await app.state.redis.close()
    await engine.dispose()


app = FastAPI(title="Breakdown", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router)
app.include_router(repos_router)
app.include_router(tasks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (existing tests for repos and tc_client should still pass).

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: wire task engine clients and router into main"
```

---

## Task 9: Smoke test

Requires: running Postgres (port 5433), Redis, and TerseContext (port 8090).

- [ ] **Step 1: Start the server**

```bash
uvicorn app.main:app --reload --port 8000
```

Expected: server starts, no errors in console.

- [ ] **Step 2: Submit a task**

```bash
curl -s -X POST http://localhost:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -H 'X-User: admin' \
  -d '{"feature_name":"ts-parser","description":"Add TypeScript support to the parser service.","repo":"tersecontext"}' \
  | python -m json.tool
```

Expected: 201, `"state": "submitted"`, valid UUID in `id`.

- [ ] **Step 3: Poll until researched (wait 10-15 seconds)**

```bash
curl -s http://localhost:8000/api/tasks/<id> -H 'X-User: admin' | python -m json.tool
```

Expected: `"state": "researched"`, `research` field populated with `summary`, `affected_code`, `complexity`, `metrics`.

- [ ] **Step 4: Approve**

```bash
curl -s -X POST http://localhost:8000/api/tasks/<id>/approve -H 'X-User: admin' | python -m json.tool
```

Expected: `"state": "approved"`.

- [ ] **Step 5: Verify Redis**

```bash
redis-cli XRANGE stream:breakdown-approved - +
```

Expected: one entry with the full bundle fields.

- [ ] **Step 6: Verify member cannot approve**

```bash
curl -s -X POST http://localhost:8000/api/tasks/<id>/approve -H 'X-User: kmcbeth'
```

Expected: `{"detail": "Admin required"}`, status 403 (need a non-admin user — create one first: `curl -X POST http://localhost:8000/api/users -H 'Content-Type: application/json' -d '{"username":"kmcbeth","role":"member"}'`).
