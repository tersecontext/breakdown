# Fracture Results Consumer — Design Spec

**Date:** 2026-04-01
**Status:** Approved

## Goal

When fracture finishes processing an approved task (success or failure), breakdown reads the result from `stream:fracture-results`, updates the task state in the database, writes a log entry, and — on failure — posts an error notification to the task's Slack thread.

---

## Architecture

Five files are affected:

| File | Change |
|------|--------|
| `app/clients/redis.py` | Add `read_fracture_results()` async generator |
| `app/engine/fracture_consumer.py` | New file — consumer loop function |
| `app/main.py` | Store `AsyncWebClient` in `app.state`; spawn/cancel consumer loop |
| `app/models.py` | No change — `state` is a plain string |
| `frontend/src/components/StateBadge.tsx` | Add `decomposed` to color map |

---

## Components

### `app/clients/redis.py` — `read_fracture_results()`

An async generator method on `RedisQueue` that:

- Calls `xgroup_create` with `mkstream=True`; ignores `BUSYGROUP` errors (group already exists)
- Calls `xreadgroup` with `group="breakdown"`, `block=1000` (1 s cap for responsive shutdown), `count=1`
- Yields `(msg_id, decoded_fields)` pairs
- Decodes bytes keys/values to strings (mirrors fracture's `_decode_message`)
- Caller is responsible for acking

### `app/engine/fracture_consumer.py` — `consume_fracture_results(app_state)`

A standalone async function (not a class) that:

- Loops calling `app_state.redis.read_fracture_results()`
- For each message:
  - Looks up the task by `task_id` in the DB via `AsyncSessionLocal`
  - If not found: logs a warning, acks, continues
  - If `status == "ok"`: sets `task.state = "decomposed"`, writes `TaskLog(event="decomposed")`, commits, acks
  - If `status == "error"`: sets `task.state = "failed"`, sets `task.error_message = msg["error"]`, writes `TaskLog(event="fracture_failed", detail={"error": ...})`, commits, calls `post_error(task, app_state.slack_web_client)`, acks
  - Acks in all cases (including task-not-found and DB errors) to avoid poison-pill loops
- Wraps the entire loop in `try/except` to log unexpected crashes before re-raising

### `app/main.py`

In `lifespan`:

1. After the Slack tokens are confirmed present, create `AsyncWebClient(token=settings.slack_bot_token)` and store it as `app.state.slack_web_client` (set to `None` if no token)
2. Spawn `consume_fracture_results(app.state)` as an `asyncio.Task` stored in a dedicated variable (not in `background_tasks`, since it must be explicitly cancelled — not just GC'd)
3. On shutdown: call `consumer_task.cancel()` and `await` it (suppress `CancelledError`)

### `frontend/src/components/StateBadge.tsx`

Add `decomposed: '#7c3aed'` (purple) to `STATE_COLORS` so the new state renders distinctly from existing states.

---

## Data Flow

```
fracture writes → stream:fracture-results
                         ↓
              consume_fracture_results loop
                         ↓
         xreadgroup(group="breakdown", block=1000ms)
                         ↓
              look up task by task_id in DB
                         ↓
       status == "ok"            status == "error"
            ↓                          ↓
  task.state = "decomposed"   task.state = "failed"
  TaskLog("decomposed")       task.error_message = msg["error"]
  commit → ack                TaskLog("fracture_failed")
                              commit
                              post_error(task, slack_web_client)
                              ack
```

No Slack notification is sent on success.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Task not found in DB | Log warning, ack, continue |
| DB commit fails | Log exception, ack, continue |
| `post_error` raises | Log exception, ack, continue |
| Slack not configured (`slack_web_client is None`) | `post_error` returns early (guarded by `source_channel != "slack"` check) |
| Consumer loop crashes unexpectedly | Top-level `try/except` logs and re-raises; lifespan shutdown still calls `cancel()` cleanly |

---

## Testing

### `tests/test_redis_client.py` (additions)

- `read_fracture_results` creates group on first call
- `BUSYGROUP` error on `xgroup_create` is silently ignored
- Messages are decoded from bytes to strings
- Empty xreadgroup result yields nothing

### `tests/test_fracture_consumer.py` (new)

- `status == "ok"`: task state set to `"decomposed"`, correct TaskLog event written, `post_error` not called, message acked
- `status == "error"`: task state set to `"failed"`, `error_message` set, `TaskLog("fracture_failed")` written, `post_error` called with task and slack client, message acked
- Task not found: warning logged, message acked, no DB writes
- DB commit failure: exception logged, message acked

---

## Fracture Output Message Fields

As written by `fracture/src/fracture/consumer.py`:

| Field | Type | Present when |
|-------|------|-------------|
| `task_id` | string | always |
| `status` | `"ok"` \| `"error"` | always |
| `error` | string | `status == "error"` |
| `decomposition_id` | string | `status == "ok"` |
| `bead_ids` | JSON string (list) | `status == "ok"` |
| `unit_count` | string (int) | `status == "ok"` |
| `phases` | JSON string (list) | `status == "ok"` |
| `conflicts` | JSON string (list) | `status == "ok"` |

Breakdown only uses `task_id`, `status`, and `error` — the bead/phase data is owned by fracture's beads store.
