# Fracture Results Consumer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume `stream:fracture-results` in Breakdown so that when Fracture finishes processing a task, the task state is updated and — on failure — a Slack error is posted.

**Architecture:** A standalone async function `consume_fracture_results(app_state)` runs as a long-lived `asyncio.Task` spawned during FastAPI lifespan. It loops calling `app_state.redis.read_fracture_results()` (a single-poll async generator on `RedisQueue`), updates task state in Postgres, writes a `TaskLog`, and on error optionally calls `post_error`. All messages are acked in a `finally` block. A persistent `AsyncWebClient` is stored on `app.state.slack_web_client` for the consumer to use.

**Tech Stack:** Python 3.12, FastAPI lifespan, redis-py asyncio (`aioredis`), SQLAlchemy asyncio, slack-sdk `AsyncWebClient`, pytest with `asyncio_mode = "auto"`, `unittest.mock`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/clients/redis.py` | Modify | Add `read_fracture_results()` generator and `ack_fracture_result()` |
| `app/engine/fracture_consumer.py` | Create | Consumer loop + per-message handler |
| `app/main.py` | Modify | Store `AsyncWebClient`, spawn/cancel consumer task |
| `frontend/src/components/StateBadge.tsx` | Modify | Add `decomposed` color |
| `tests/test_redis_client.py` | Modify | Tests for the two new `RedisQueue` methods |
| `tests/test_fracture_consumer.py` | Create | Tests for `_handle_message` |

---

## Task 1: `read_fracture_results()` and `ack_fracture_result()` on `RedisQueue`

**Files:**
- Modify: `app/clients/redis.py`
- Modify: `tests/test_redis_client.py`

These tests mock `aioredis.from_url` (same pattern as the existing `test_push_approved_xadds_to_stream` test). Add the four new tests to the bottom of `tests/test_redis_client.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_redis_client.py`:

```python
import socket


async def test_read_fracture_results_creates_consumer_group():
    """xgroup_create is called with mkstream=True on the fracture stream"""
    mock_redis = AsyncMock()
    mock_redis.xreadgroup.return_value = []

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        async for _ in q.read_fracture_results():
            pass

    mock_redis.xgroup_create.assert_called_once_with(
        "stream:fracture-results", "breakdown", id="0", mkstream=True
    )


async def test_read_fracture_results_ignores_busygroup():
    """BUSYGROUP error from xgroup_create is silently ignored"""
    mock_redis = AsyncMock()
    mock_redis.xgroup_create.side_effect = Exception("BUSYGROUP Consumer Group name already exists")
    mock_redis.xreadgroup.return_value = []

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        # Should not raise
        async for _ in q.read_fracture_results():
            pass


async def test_read_fracture_results_decodes_bytes_to_strings():
    """Bytes keys and values in stream messages are decoded to str"""
    msg_id = b"1234567890-0"
    raw_fields = {b"task_id": b"abc-123", b"status": b"ok"}
    mock_redis = AsyncMock()
    mock_redis.xreadgroup.return_value = [
        (b"stream:fracture-results", [(msg_id, raw_fields)])
    ]

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        messages = [(mid, fields) async for mid, fields in q.read_fracture_results()]

    assert len(messages) == 1
    returned_id, returned_fields = messages[0]
    assert returned_id == msg_id
    assert returned_fields == {"task_id": "abc-123", "status": "ok"}


async def test_read_fracture_results_empty_response_yields_nothing():
    """Empty xreadgroup response (timeout) yields no messages"""
    mock_redis = AsyncMock()
    mock_redis.xreadgroup.return_value = []

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        messages = [m async for m in q.read_fracture_results()]

    assert messages == []


async def test_ack_fracture_result_calls_xack():
    """ack_fracture_result() calls xack on the fracture stream with the breakdown group"""
    mock_redis = AsyncMock()

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        await q.ack_fracture_result(b"1234567890-0")

    mock_redis.xack.assert_called_once_with(
        "stream:fracture-results", "breakdown", b"1234567890-0"
    )
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd /home/kmcbeth/maintainer/breakdown
python -m pytest tests/test_redis_client.py -v -k "fracture"
```

Expected: 5 failures — `AttributeError: 'RedisQueue' object has no attribute 'read_fracture_results'`

- [ ] **Step 3: Implement `read_fracture_results()` and `ack_fracture_result()`**

Replace the full contents of `app/clients/redis.py` with:

```python
import json
import socket

import redis.asyncio as aioredis

COMPLEX_FIELDS = {"research", "additional_context", "optional_answers"}

_FRACTURE_STREAM = "stream:fracture-results"
_FRACTURE_GROUP = "breakdown"


class RedisQueue:
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)

    async def push_approved(self, bundle: dict) -> None:
        fields = {
            k: json.dumps(v) if k in COMPLEX_FIELDS else str(v)
            for k, v in bundle.items()
        }
        await self._redis.xadd("stream:breakdown-approved", fields)

    async def read_fracture_results(self):
        """Single-poll async generator. Yields (msg_id, decoded_fields) for each
        message returned by one xreadgroup call. Blocks up to 1 s for new messages.
        Caller loops and calls this repeatedly; caller is responsible for acking."""
        try:
            await self._redis.xgroup_create(
                _FRACTURE_STREAM, _FRACTURE_GROUP, id="0", mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        consumer = socket.gethostname()
        results = await self._redis.xreadgroup(
            _FRACTURE_GROUP,
            consumer,
            {_FRACTURE_STREAM: ">"},
            count=1,
            block=1000,
        )
        if not results:
            return
        for _stream, messages in results:
            for msg_id, fields in messages:
                decoded = {
                    (k.decode() if isinstance(k, bytes) else k): (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in fields.items()
                }
                yield msg_id, decoded

    async def ack_fracture_result(self, msg_id) -> None:
        await self._redis.xack(_FRACTURE_STREAM, _FRACTURE_GROUP, msg_id)

    async def close(self) -> None:
        await self._redis.aclose()
```

- [ ] **Step 4: Run all redis client tests to confirm they pass**

```bash
python -m pytest tests/test_redis_client.py -v
```

Expected: all 7 tests pass (2 existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add app/clients/redis.py tests/test_redis_client.py
git commit -m "feat: add read_fracture_results and ack_fracture_result to RedisQueue"
```

---

## Task 2: `app/engine/fracture_consumer.py`

**Files:**
- Create: `app/engine/fracture_consumer.py`
- Create: `tests/test_fracture_consumer.py`

The public entry point is `consume_fracture_results(app_state)`. The per-message logic lives in `_handle_message(msg_id, fields, app_state)` — a module-level async function that is tested directly. Tests mock `AsyncSessionLocal` as an async context manager and patch `post_error`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fracture_consumer.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app_state(slack_client=None):
    state = MagicMock()
    state.redis = AsyncMock()
    state.slack_web_client = slack_client
    return state


def make_task(task_id, source_channel="slack"):
    task = MagicMock()
    task.id = task_id
    task.state = "approved"
    task.error_message = None
    task.source_channel = source_channel
    task.slack_channel_id = "C123"
    task.slack_thread_ts = "111.222"
    task.feature_name = "test feature"
    return task


def make_session_mock(task):
    """Return a mock AsyncSessionLocal that yields a session whose execute()
    returns the given task (or None if task is None)."""
    session = AsyncMock()
    session.execute.return_value.scalar_one_or_none.return_value = task
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session)
    return session_factory, session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_ok_message_sets_state_decomposed():
    """status=ok sets task.state='decomposed', writes TaskLog, acks, no post_error"""
    task_id = uuid.uuid4()
    task = make_task(task_id)
    app_state = make_app_state(slack_client=AsyncMock())
    session_factory, session = make_session_mock(task)
    msg_id = b"1-0"
    fields = {"task_id": str(task_id), "status": "ok"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    assert task.state == "decomposed"
    assert task.error_message is None
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.event == "decomposed"
    session.commit.assert_called_once()
    mock_post_error.assert_not_called()
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_error_message_sets_state_failed():
    """status=error sets task.state='failed', sets error_message, writes TaskLog,
    calls post_error, acks"""
    task_id = uuid.uuid4()
    task = make_task(task_id)
    slack_client = AsyncMock()
    app_state = make_app_state(slack_client=slack_client)
    session_factory, session = make_session_mock(task)
    msg_id = b"2-0"
    fields = {"task_id": str(task_id), "status": "error", "error": "pipeline crashed"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    assert task.state == "failed"
    assert task.error_message == "pipeline crashed"
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.event == "fracture_failed"
    assert added.detail == {"error": "pipeline crashed"}
    session.commit.assert_called_once()
    mock_post_error.assert_called_once_with(task, slack_client)
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_task_not_found_acks_without_db_writes():
    """If task_id is not in the DB, logs a warning and acks — no state changes"""
    task_id = uuid.uuid4()
    app_state = make_app_state()
    session_factory, session = make_session_mock(task=None)
    msg_id = b"3-0"
    fields = {"task_id": str(task_id), "status": "ok"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error, \
         patch("app.engine.fracture_consumer.logger") as mock_logger:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    session.add.assert_not_called()
    session.commit.assert_not_called()
    mock_post_error.assert_not_called()
    mock_logger.warning.assert_called()
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_db_commit_failure_still_acks():
    """If session.commit() raises, the message is still acked"""
    task_id = uuid.uuid4()
    task = make_task(task_id)
    app_state = make_app_state()
    session_factory, session = make_session_mock(task)
    session.commit.side_effect = Exception("DB connection lost")
    msg_id = b"4-0"
    fields = {"task_id": str(task_id), "status": "ok"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error"):
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_slack_client_none_does_not_call_post_error():
    """When slack_web_client is None and status=error, post_error is not called"""
    task_id = uuid.uuid4()
    task = make_task(task_id, source_channel="slack")
    app_state = make_app_state(slack_client=None)
    session_factory, session = make_session_mock(task)
    msg_id = b"5-0"
    fields = {"task_id": str(task_id), "status": "error", "error": "boom"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    # No crash, acked, post_error not called
    mock_post_error.assert_not_called()
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)
    assert task.state == "failed"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
python -m pytest tests/test_fracture_consumer.py -v
```

Expected: 5 failures — `ModuleNotFoundError: No module named 'app.engine.fracture_consumer'`

- [ ] **Step 3: Implement `app/engine/fracture_consumer.py`**

Create `app/engine/fracture_consumer.py`:

```python
"""fracture_consumer.py — Consumes stream:fracture-results and updates task state."""
import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.engine.notifier import post_error
from app.models import Task, TaskLog

logger = logging.getLogger(__name__)


async def consume_fracture_results(app_state) -> None:
    """Long-running loop. Reads stream:fracture-results and updates task state.

    Spawned as an asyncio.Task in lifespan. Exits cleanly on CancelledError.
    """
    logger.info("Fracture results consumer started")
    while True:
        try:
            async for msg_id, fields in app_state.redis.read_fracture_results():
                await _handle_message(msg_id, fields, app_state)
        except asyncio.CancelledError:
            logger.info("Fracture results consumer cancelled")
            raise
        except Exception:
            logger.exception("Unexpected error in fracture results consumer")
            raise


async def _handle_message(msg_id, fields: dict, app_state) -> None:
    """Process one message from stream:fracture-results.

    Always acks (in finally) to prevent poison-pill loops.
    """
    task_id_str = fields.get("task_id", "")
    status = fields.get("status", "")

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Task).where(Task.id == UUID(task_id_str))
            )
            task = result.scalar_one_or_none()

            if task is None:
                logger.warning(
                    "fracture_consumer: task %s not found — skipping", task_id_str
                )
                return

            if status == "ok":
                task.state = "decomposed"
                session.add(TaskLog(task_id=task.id, event="decomposed"))
                await session.commit()

            elif status == "error":
                error_text = fields.get("error", "unknown error")
                task.state = "failed"
                task.error_message = error_text
                session.add(TaskLog(
                    task_id=task.id,
                    event="fracture_failed",
                    detail={"error": error_text},
                ))
                await session.commit()
                if app_state.slack_web_client is not None:
                    try:
                        await post_error(task, app_state.slack_web_client)
                    except Exception:
                        logger.exception(
                            "fracture_consumer: post_error failed for task %s", task_id_str
                        )

            else:
                logger.warning(
                    "fracture_consumer: unknown status %r for task %s", status, task_id_str
                )

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "fracture_consumer: error handling message for task %s", task_id_str
        )
    finally:
        await app_state.redis.ack_fracture_result(msg_id)
```

- [ ] **Step 4: Run all fracture consumer tests to confirm they pass**

```bash
python -m pytest tests/test_fracture_consumer.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/engine/fracture_consumer.py tests/test_fracture_consumer.py
git commit -m "feat: add fracture results consumer"
```

---

## Task 3: Wire up `app/main.py`

**Files:**
- Modify: `app/main.py`

This task has no new unit tests — the integration is thin wiring code. Verification is done by running the full test suite.

The changes to `main.py`:

1. Store a persistent `AsyncWebClient` on `app.state.slack_web_client` (reusing it for the existing channel-lookup instead of creating and immediately closing an ephemeral one).
2. Spawn `consume_fracture_results` as a dedicated `consumer_task` (separate from `background_tasks`).
3. Cancel and await the consumer on shutdown, then close the slack web client.

- [ ] **Step 1: Apply the changes to `app/main.py`**

The full updated `app/main.py`:

```python
import asyncio
import logging
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
from app.engine.fracture_consumer import consume_fracture_results
from app.models import User
from app.routes.repos import router as repos_router
from app.routes.tasks import router as tasks_router
from app.routes.users import router as users_router

logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    proc = await asyncio.create_subprocess_exec("alembic", "upgrade", "head")
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed with code {proc.returncode}")


async def seed_admin() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        if result.first() is None:
            username = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
            session.add(User(username=username, role="admin"))
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    await seed_admin()
    app.state.tc_client = TerseContextClient(settings.tersecontext_url)
    app.state.llm_client = AnthropicClient(settings.anthropic_api_key, settings.default_model)
    app.state.redis = RedisQueue(settings.redis_url)
    app.state.background_tasks = set()  # holds references to prevent GC

    # Persistent Slack web client — used by fracture consumer for error notifications.
    # Also used below for channel-id lookup (replaces the previous ephemeral client).
    app.state.slack_web_client = None
    if settings.slack_bot_token:
        from slack_sdk.web.async_client import AsyncWebClient
        app.state.slack_web_client = AsyncWebClient(token=settings.slack_bot_token)

    slack_bot = None
    if settings.slack_bot_token and settings.slack_app_token:
        try:
            from app.clients.slack_bot import SlackBot

            channel_id = None
            try:
                cursor = None
                while channel_id is None:
                    resp = await app.state.slack_web_client.conversations_list(
                        exclude_archived=True, limit=200, cursor=cursor
                    )
                    for ch in resp["channels"]:
                        if ch["name"] == settings.slack_channel:
                            channel_id = ch["id"]
                            break
                    cursor = resp.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
            except Exception:
                logger.exception("Failed to look up Slack channel ID")

            if channel_id is None:
                logger.warning(
                    "Slack channel '%s' not found; bot will not start", settings.slack_channel
                )
            else:
                slack_bot = SlackBot(app.state, channel_id=channel_id)
                await slack_bot.start()
                logger.info("Slack bot started (channel=%s)", channel_id)
        except Exception:
            logger.exception("Failed to start Slack bot")

    # Fracture results consumer — runs for the lifetime of the process.
    consumer_task = asyncio.create_task(consume_fracture_results(app.state))

    yield

    # ── Shutdown ────────────────────────────────────────────────────────────
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    if slack_bot is not None:
        await slack_bot.stop()
    await app.state.tc_client.close()
    await app.state.redis.close()
    if app.state.slack_web_client is not None:
        await app.state.slack_web_client.session.close()
    await engine.dispose()


app = FastAPI(title="Breakdown", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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

**Key changes vs. the original:**
- Added `from app.engine.fracture_consumer import consume_fracture_results`
- `app.state.slack_web_client` created early from `settings.slack_bot_token` (no token → `None`)
- The channel-lookup loop now uses `app.state.slack_web_client` directly (no separate ephemeral `web_client`); the `finally: await web_client.session.close()` block is removed
- `consumer_task = asyncio.create_task(consume_fracture_results(app.state))` spawned before `yield`
- Shutdown: `consumer_task.cancel()` + suppress `CancelledError`, then `app.state.slack_web_client.session.close()`

- [ ] **Step 2: Run the full test suite to confirm nothing is broken**

```bash
python -m pytest tests/ -v --ignore=tests/test_fracture_consumer.py --ignore=tests/test_redis_client.py -x
```

Expected: all existing tests pass.

- [ ] **Step 3: Run the complete test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: wire fracture consumer and persistent Slack web client in lifespan"
```

---

## Task 4: Add `decomposed` to `StateBadge`

**Files:**
- Modify: `frontend/src/components/StateBadge.tsx`

No frontend tests exist for this component. Visual verification is manual.

- [ ] **Step 1: Add `decomposed` to `STATE_COLORS`**

In `frontend/src/components/StateBadge.tsx`, update the `STATE_COLORS` object:

```tsx
const STATE_COLORS: Record<string, string> = {
  submitted: '#6b7280',
  researching: '#d97706',
  researched: '#2563eb',
  approved: '#16a34a',
  rejected: '#dc2626',
  failed: '#dc2626',
  decomposed: '#7c3aed',
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/StateBadge.tsx
git commit -m "feat: add decomposed state color to StateBadge"
```

---

## Final Verification

- [ ] **Run the full test suite one last time**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass with no warnings about missing fixtures or import errors.
