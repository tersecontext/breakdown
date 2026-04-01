# Resubmit Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the original submitter (or an admin) to edit and resubmit a rejected task, re-triggering research with the updated fields.

**Architecture:** New `POST /api/tasks/{id}/resubmit` endpoint that updates editable fields, resets state to `submitted`, clears prior research, and re-runs the research background task — mirroring the existing `retry` pattern. Frontend adds an inline edit form on the rejected task detail page, gated to the submitter or admin.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), React + TypeScript (frontend), pytest-asyncio (tests)

---

## File Map

| File | Change |
|------|--------|
| `app/schemas.py` | Add `TaskResubmit` schema |
| `app/routes/tasks.py` | Add `resubmit_task` endpoint |
| `tests/test_tasks.py` | Add resubmit endpoint tests |
| `frontend/src/types.ts` | Add `TaskResubmit` interface |
| `frontend/src/pages/Login.tsx` | Store `user_id` in localStorage at login |
| `frontend/src/api.ts` | Add `resubmitTask` function |
| `frontend/src/pages/TaskDetail.tsx` | Add inline edit & resubmit UI |

---

## Task 1: Backend schema

**Files:**
- Modify: `app/schemas.py`

- [ ] **Step 1: Add `TaskResubmit` schema to `app/schemas.py`**

  Insert after the `TaskReject` class (line 97):

  ```python
  class TaskResubmit(BaseModel):
      feature_name: str | None = None
      description: str | None = None
      repo: str | None = None
      branch_from: str | None = None
      additional_context: list[str] | None = None
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add app/schemas.py
  git commit -m "feat: add TaskResubmit schema"
  ```

---

## Task 2: Backend endpoint (TDD)

**Files:**
- Modify: `tests/test_tasks.py`
- Modify: `app/routes/tasks.py`

- [ ] **Step 1: Write failing tests**

  Append to `tests/test_tasks.py`:

  ```python
  # --- resubmit ---

  @pytest.mark.asyncio
  async def test_resubmit_task_resets_state_and_reruns_research(app_client, db_session):
      from app.main import app as fastapi_app
      user = await make_user(db_session, "resubmit1")
      task = await make_task(db_session, user, state="rejected")
      fastapi_app.state.tc_client = AsyncMock()
      fastapi_app.state.llm_client = AsyncMock()
      fastapi_app.state.background_tasks = set()

      with patch("app.routes.tasks.asyncio.create_task") as mock_create_task:
          response = await app_client.post(
              f"/api/tasks/{task.id}/resubmit",
              json={"feature_name": "updated-name", "description": "updated desc"},
              headers=auth_header(user),
          )

      assert response.status_code == 200
      data = response.json()
      assert data["state"] == "submitted"
      assert data["feature_name"] == "updated-name"
      assert data["description"] == "updated desc"
      # unchanged fields keep original values
      assert data["repo"] == "tersecontext"
      mock_create_task.assert_called_once()


  @pytest.mark.asyncio
  async def test_resubmit_task_clears_research_and_error(app_client, db_session):
      from app.main import app as fastapi_app
      user = await make_user(db_session, "resubmit2")
      task = await make_task(db_session, user, state="rejected", research={"summary": "old"})
      task.error_message = "old error"
      task.tc_context = "old context"
      await db_session.flush()
      fastapi_app.state.tc_client = AsyncMock()
      fastapi_app.state.llm_client = AsyncMock()
      fastapi_app.state.background_tasks = set()

      with patch("app.routes.tasks.asyncio.create_task"):
          response = await app_client.post(
              f"/api/tasks/{task.id}/resubmit",
              json={},
              headers=auth_header(user),
          )

      assert response.status_code == 200
      data = response.json()
      assert data["research"] is None
      assert data["error_message"] is None


  @pytest.mark.asyncio
  async def test_resubmit_task_returns_404_when_not_found(app_client, db_session):
      user = await make_user(db_session, "resubmit3")
      response = await app_client.post(
          f"/api/tasks/{uuid.uuid4()}/resubmit",
          json={},
          headers=auth_header(user),
      )
      assert response.status_code == 404


  @pytest.mark.asyncio
  async def test_resubmit_task_returns_409_when_not_rejected(app_client, db_session):
      from app.main import app as fastapi_app
      user = await make_user(db_session, "resubmit4")
      task = await make_task(db_session, user, state="researched")
      fastapi_app.state.background_tasks = set()
      response = await app_client.post(
          f"/api/tasks/{task.id}/resubmit",
          json={},
          headers=auth_header(user),
      )
      assert response.status_code == 409


  @pytest.mark.asyncio
  async def test_resubmit_task_returns_403_for_non_submitter(app_client, db_session):
      owner = await make_user(db_session, "resubmit5-owner")
      other = await make_user(db_session, "resubmit5-other")
      task = await make_task(db_session, owner, state="rejected")
      response = await app_client.post(
          f"/api/tasks/{task.id}/resubmit",
          json={},
          headers=auth_header(other),
      )
      assert response.status_code == 403


  @pytest.mark.asyncio
  async def test_resubmit_task_allowed_for_admin(app_client, db_session):
      from app.main import app as fastapi_app
      owner = await make_user(db_session, "resubmit6-owner")
      admin = await make_user(db_session, "resubmit6-admin", role="admin")
      task = await make_task(db_session, owner, state="rejected")
      fastapi_app.state.tc_client = AsyncMock()
      fastapi_app.state.llm_client = AsyncMock()
      fastapi_app.state.background_tasks = set()

      with patch("app.routes.tasks.asyncio.create_task"):
          response = await app_client.post(
              f"/api/tasks/{task.id}/resubmit",
              json={},
              headers=auth_header(admin),
          )

      assert response.status_code == 200


  @pytest.mark.asyncio
  async def test_resubmit_task_logs_resubmitted_event(app_client, db_session):
      from app.main import app as fastapi_app
      user = await make_user(db_session, "resubmit7")
      task = await make_task(db_session, user, state="rejected")
      fastapi_app.state.tc_client = AsyncMock()
      fastapi_app.state.llm_client = AsyncMock()
      fastapi_app.state.background_tasks = set()

      with patch("app.routes.tasks.asyncio.create_task"):
          response = await app_client.post(
              f"/api/tasks/{task.id}/resubmit",
              json={},
              headers=auth_header(user),
          )

      assert response.status_code == 200
      log_events = [log["event"] for log in response.json()["logs"]]
      assert "task_resubmitted" in log_events
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  pytest tests/test_tasks.py -k "resubmit" -v
  ```

  Expected: all 7 tests FAIL with `404` (route doesn't exist yet)

- [ ] **Step 3: Implement `resubmit_task` endpoint in `app/routes/tasks.py`**

  Add the import for `TaskResubmit` at the top (update the existing schemas import line):

  ```python
  from app.schemas import TaskCreate, TaskListItem, TaskOut, TaskReject, TaskResubmit
  ```

  Then add this endpoint after the `retry_task` handler (after the closing of that function, before `approve_task`):

  ```python
  @router.post("/api/tasks/{task_id}/resubmit", response_model=TaskOut)
  async def resubmit_task(
      task_id: UUID,
      body: TaskResubmit,
      request: Request,
      user: User = Depends(get_current_user),
      session: AsyncSession = Depends(get_session),
  ):
      result = await session.execute(
          select(Task).where(Task.id == task_id).options(selectinload(Task.logs), selectinload(Task.submitter))
      )
      task = result.scalar_one_or_none()
      if task is None:
          raise HTTPException(status_code=404, detail="Task not found")
      if task.state != "rejected":
          raise HTTPException(status_code=409, detail=f"Task is in state '{task.state}', expected 'rejected'")
      if task.submitter_id != user.id and user.role != "admin":
          raise HTTPException(status_code=403, detail="Only the original submitter or an admin can resubmit")

      if body.feature_name is not None:
          task.feature_name = body.feature_name
      if body.description is not None:
          task.description = body.description
      if body.repo is not None:
          task.repo = body.repo
      if body.branch_from is not None:
          task.branch_from = body.branch_from
      if body.additional_context is not None:
          task.additional_context = body.additional_context

      task.state = "submitted"
      task.error_message = None
      task.tc_context = None
      task.research = None
      session.add(TaskLog(task_id=task.id, event="task_resubmitted", actor_id=user.id))
      await session.commit()

      result = await session.execute(
          select(Task).where(Task.id == task.id).options(selectinload(Task.logs), selectinload(Task.submitter))
      )
      task = result.scalar_one()

      t = asyncio.create_task(
          research(task.id, request.app.state.tc_client, request.app.state.llm_client)
      )
      request.app.state.background_tasks.add(t)
      t.add_done_callback(request.app.state.background_tasks.discard)

      return task
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  pytest tests/test_tasks.py -k "resubmit" -v
  ```

  Expected: all 7 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

  ```bash
  pytest tests/test_tasks.py -v
  ```

  Expected: all tests PASS

- [ ] **Step 6: Commit**

  ```bash
  git add app/routes/tasks.py tests/test_tasks.py
  git commit -m "feat: add POST /api/tasks/{id}/resubmit endpoint"
  ```

---

## Task 3: Frontend types, API, and Login

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Add `TaskResubmit` interface to `frontend/src/types.ts`**

  Append after the `TaskCreate` interface (after line 103):

  ```typescript
  export interface TaskResubmit {
    feature_name?: string;
    description?: string;
    repo?: string;
    branch_from?: string;
    additional_context?: string[];
  }
  ```

- [ ] **Step 2: Store `user_id` at login in `frontend/src/pages/Login.tsx`**

  Find the lines that set localStorage after a successful login (around line 20):

  ```typescript
  localStorage.setItem('role', data.user.role)
  ```

  Replace with:

  ```typescript
  localStorage.setItem('role', data.user.role)
  localStorage.setItem('user_id', data.user.id)
  ```

- [ ] **Step 3: Add `resubmitTask` to `frontend/src/api.ts`**

  First, update the import line at the top to include `TaskResubmit`:

  ```typescript
  import type { RepoInfo, RefreshResponse, TaskCreate, TaskListItem, TaskOut, TaskResubmit, TokenResponse, User } from './types';
  ```

  Then append after `rejectTask`:

  ```typescript
  export const resubmitTask = (id: string, fields: TaskResubmit): Promise<TaskOut> =>
    apiFetch(`/api/tasks/${id}/resubmit`, {
      method: 'POST',
      body: JSON.stringify(fields),
    });
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/types.ts frontend/src/pages/Login.tsx frontend/src/api.ts
  git commit -m "feat: add TaskResubmit type, store user_id at login, add resubmitTask api call"
  ```

---

## Task 4: Frontend TaskDetail UI

**Files:**
- Modify: `frontend/src/pages/TaskDetail.tsx`

- [ ] **Step 1: Add `resubmitTask` to the import in `TaskDetail.tsx`**

  Find the existing api import line:

  ```typescript
  import { approveTask, rejectTask, retryTask, getTask } from '../api'
  ```

  Replace with:

  ```typescript
  import { approveTask, rejectTask, resubmitTask, retryTask, getTask } from '../api'
  ```

- [ ] **Step 2: Add resubmit state variables**

  Find the existing state declarations block (the `useState` calls near the top of the component, around lines 13–17):

  ```typescript
  const [acting, setActing] = useState(false)
  const role = localStorage.getItem('role') ?? 'member'
  const isAdmin = role === 'admin'
  ```

  Replace with:

  ```typescript
  const [acting, setActing] = useState(false)
  const [resubmitting, setResubmitting] = useState(false)
  const [resubmitFields, setResubmitFields] = useState<{
    feature_name: string; description: string; repo: string;
    branch_from: string; additional_context: string;
  } | null>(null)
  const role = localStorage.getItem('role') ?? 'member'
  const isAdmin = role === 'admin'
  const currentUserId = localStorage.getItem('user_id')
  ```

- [ ] **Step 3: Add `task_resubmitted` to `STEP_LABELS`**

  Find the `STEP_LABELS` object inside the in-progress spinner block:

  ```typescript
  const STEP_LABELS: Record<string, string> = {
    task_created: 'Queued…',
    task_retried: 'Queued…',
  ```

  Replace with:

  ```typescript
  const STEP_LABELS: Record<string, string> = {
    task_created: 'Queued…',
    task_retried: 'Queued…',
    task_resubmitted: 'Queued…',
  ```

- [ ] **Step 4: Add the Edit & Resubmit UI block**

  Find the `{task.state === 'rejected' && (` block that renders the rejected banner:

  ```typescript
  {task.state === 'rejected' && (
    <div style={{
      display: 'inline-block', marginBottom: 16, padding: '4px 12px', borderRadius: 4,
      background: '#fee2e2', color: '#dc2626', fontSize: 13, fontWeight: 600,
    }}>
      ✗ Rejected
    </div>
  )}
  ```

  Replace with:

  ```typescript
  {task.state === 'rejected' && (
    <div>
      <div style={{
        display: 'inline-block', marginBottom: 16, padding: '4px 12px', borderRadius: 4,
        background: '#fee2e2', color: '#dc2626', fontSize: 13, fontWeight: 600,
      }}>
        ✗ Rejected
      </div>
      {(isAdmin || currentUserId === task.submitter_id) && (
        resubmitting ? (
          <div style={{ marginTop: 16 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <input
                value={resubmitFields?.feature_name ?? ''}
                onChange={e => setResubmitFields(f => f ? { ...f, feature_name: e.target.value } : f)}
                placeholder="Feature name"
                style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
              />
              <textarea
                value={resubmitFields?.description ?? ''}
                onChange={e => setResubmitFields(f => f ? { ...f, description: e.target.value } : f)}
                placeholder="Description"
                rows={3}
                style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
              />
              <input
                value={resubmitFields?.repo ?? ''}
                onChange={e => setResubmitFields(f => f ? { ...f, repo: e.target.value } : f)}
                placeholder="Repo"
                style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
              />
              <input
                value={resubmitFields?.branch_from ?? ''}
                onChange={e => setResubmitFields(f => f ? { ...f, branch_from: e.target.value } : f)}
                placeholder="Branch"
                style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
              />
              <textarea
                value={resubmitFields?.additional_context ?? ''}
                onChange={e => setResubmitFields(f => f ? { ...f, additional_context: e.target.value } : f)}
                placeholder="Additional context (one item per line)"
                rows={3}
                style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
              />
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button
                onClick={async () => {
                  if (!id || !resubmitFields) return
                  setActing(true)
                  try {
                    const fields = {
                      feature_name: resubmitFields.feature_name || undefined,
                      description: resubmitFields.description || undefined,
                      repo: resubmitFields.repo || undefined,
                      branch_from: resubmitFields.branch_from || undefined,
                      additional_context: resubmitFields.additional_context
                        ? resubmitFields.additional_context.split('\n').map(s => s.trim()).filter(Boolean)
                        : undefined,
                    }
                    setTask(await resubmitTask(id, fields))
                    setResubmitting(false)
                    setResubmitFields(null)
                  } catch (e) {
                    setError(String(e))
                  } finally {
                    setActing(false)
                  }
                }}
                disabled={acting}
                style={{
                  padding: '8px 20px', borderRadius: 4, background: '#111', color: '#fff',
                  border: 'none', fontSize: 14, fontWeight: 500, opacity: acting ? 0.5 : 1,
                }}
              >
                {acting ? 'Resubmitting…' : 'Resubmit'}
              </button>
              <button
                onClick={() => { setResubmitting(false); setResubmitFields(null) }}
                style={{
                  padding: '8px 16px', borderRadius: 4, background: '#f3f4f6',
                  color: '#111', border: '1px solid #d1d5db', fontSize: 14,
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 8 }}>
            <button
              onClick={() => {
                setResubmitting(true)
                setResubmitFields({
                  feature_name: task.feature_name,
                  description: task.description,
                  repo: task.repo,
                  branch_from: task.branch_from,
                  additional_context: task.additional_context.join('\n'),
                })
              }}
              style={{
                padding: '8px 20px', borderRadius: 4, background: '#fff', color: '#111',
                border: '1px solid #d1d5db', fontSize: 14, fontWeight: 500,
              }}
            >
              Edit &amp; Resubmit
            </button>
          </div>
        )
      )}
    </div>
  )}
  ```

- [ ] **Step 5: Verify TypeScript compiles without errors**

  ```bash
  cd frontend && npx tsc --noEmit
  ```

  Expected: no errors

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/pages/TaskDetail.tsx
  git commit -m "feat: add Edit & Resubmit UI for rejected tasks"
  ```

---

## Task 5: Final verification

- [ ] **Step 1: Run full backend test suite**

  ```bash
  pytest tests/ -v
  ```

  Expected: all tests PASS

- [ ] **Step 2: Commit if anything was missed**

  If any files were modified during verification:

  ```bash
  git add -p
  git commit -m "fix: address review feedback on resubmit feature"
  ```
