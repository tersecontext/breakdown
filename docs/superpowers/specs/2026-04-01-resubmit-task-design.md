# Resubmit Task — Design Spec

**Date:** 2026-04-01
**Status:** Approved

## Overview

Allow users to edit and resubmit a rejected task. This gives submitters a way to revise their request after an admin rejection without creating a duplicate task.

## Backend

### New endpoint: `POST /api/tasks/{id}/resubmit`

**Schema: `TaskResubmit`** (all fields optional, falls back to existing task values)
- `feature_name: str | None`
- `description: str | None`
- `repo: str | None`
- `branch_from: str | None`
- `additional_context: list[str] | None`

**Guards:**
- Task not found → `404`
- Task not in `rejected` state → `409`
- Caller is not the original submitter and not an admin → `403`

**Body semantics:** All fields are optional. A missing or `null` field means "leave unchanged" — the existing task value is used. `null` is never written to non-nullable columns. A provided `additional_context` list fully replaces the existing list.

**On success:**
1. Update any provided (non-null) fields on the task
2. Reset `state` to `submitted`
3. Clear `error_message`, `tc_context` (important: prior context may have been built against a different repo/branch), `research`
4. Log `task_resubmitted` event
5. Commit
6. Re-trigger research using the full three-line pattern from `POST /api/tasks/{id}/retry`:
   ```python
   t = asyncio.create_task(research(task.id, request.app.state.tc_client, request.app.state.llm_client))
   request.app.state.background_tasks.add(t)
   t.add_done_callback(request.app.state.background_tasks.discard)
   ```
7. Return updated `TaskOut`

**Auth:** Original submitter or admin only.

## Frontend

### `types.ts`

Add a `TaskResubmit` interface with all fields optional:
```ts
export interface TaskResubmit {
  feature_name?: string;
  description?: string;
  repo?: string;
  branch_from?: string;
  additional_context?: string[];
}
```

### `Login.tsx`

At login, also store the current user's ID in localStorage alongside `role`:
```ts
localStorage.setItem('role', data.user.role)
localStorage.setItem('user_id', data.user.id)
```

### `api.ts`

Add `resubmitTask(id: string, fields: TaskResubmit): Promise<TaskOut>` that calls `POST /api/tasks/{id}/resubmit` with the edited fields.

### `TaskDetail.tsx`

When `task.state === 'rejected'`:

- Read `currentUserId = localStorage.getItem('user_id')`
- Show "Edit & Resubmit" button only if `isAdmin || currentUserId === task.submitter_id`
- Clicking it toggles an inline edit form (same pattern as the reject-reason textarea)
- Form fields, pre-filled with current task values:
  - `feature_name` (text input)
  - `description` (textarea)
  - `repo` (text input)
  - `branch_from` (text input)
  - `additional_context` (textarea, newline-separated)
- Buttons: "Resubmit" (submits) and "Cancel" (collapses form)
- On submit: calls `resubmitTask`, updates task state, collapses form; on error, surfaces error message and keeps form open
- Add `task_resubmitted: 'Queued…'` to the `STEP_LABELS` map in the in-progress spinner
- Existing polling (`submitted`/`researching`) handles auto-refresh once research starts

`optional_answers` is excluded — no existing UI pattern for editing structured data.

## Out of Scope

- Allowing any authenticated user regardless of ownership to resubmit — only the original submitter or an admin may do so
- Editing `optional_answers`
- Resubmitting from states other than `rejected`
