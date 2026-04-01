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

**Guard:** Task must be in `rejected` state. Returns `409` otherwise.

**On success:**
1. Update any provided fields on the task
2. Reset `state` to `submitted`
3. Clear `error_message`, `tc_context`, `research`
4. Log `task_resubmitted` event
5. Commit
6. Re-trigger `research(...)` as a background task (same as `retry`)
7. Return updated `TaskOut`

**Auth:** Any authenticated user (same as `retry`).

## Frontend

### `api.ts`

Add `resubmitTask(id, fields)` that calls `POST /api/tasks/{id}/resubmit` with the edited fields.

### `TaskDetail.tsx`

When `task.state === 'rejected'`:

- Show an "Edit & Resubmit" button below the rejected banner
- Clicking it toggles an inline edit form (same pattern as the reject-reason textarea)
- Form fields, pre-filled with current task values:
  - `feature_name` (text input)
  - `description` (textarea)
  - `repo` (text input)
  - `branch_from` (text input)
  - `additional_context` (textarea, newline-separated)
- Buttons: "Resubmit" (submits) and "Cancel" (collapses form)
- On submit: calls `resubmitTask`, updates task state, collapses form
- Existing polling (`submitted`/`researching`) handles auto-refresh once research starts

`optional_answers` is excluded — no existing UI pattern for editing structured data.

## Out of Scope

- Admin-only resubmit restriction (any authenticated user can resubmit, same as retry)
- Editing `optional_answers`
- Resubmitting from states other than `rejected`
