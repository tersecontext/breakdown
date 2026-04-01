# Subtask 4a: React frontend

**Layer:** 4 (parallel — run alongside 4b after subtask 3 merges)
**Branch:** `feature/frontend`
**Worktree:** `../breakdown-frontend`

## Setup

```bash
cd breakdown
git worktree add -b feature/frontend ../breakdown-frontend
cp subtasks/4a-frontend/CLAUDE.md ../breakdown-frontend/SUBTASK.md
cd ../breakdown-frontend
```

## What to build

Full React web app: login, submission form, task list, research review with approve/reject.

### Initialize

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install react-router-dom
```

### API client

- Create `src/api.ts`: fetch wrapper for `/api/*`. Include `X-User` header from stored username. Functions for: login, getMe, listRepos, getBranches, listTasks, getTask, createTask, approveTask, rejectTask.

### Vite config

- `vite.config.ts`: proxy `/api` to `http://localhost:8000`

### Login page

- `src/pages/Login.tsx`:
  - Username text input + "Login" button
  - POST /api/auth/login
  - Store username in localStorage
  - Redirect to /tasks on success

### Submission form

- `src/pages/Submit.tsx` — matches the mockup from the conversation:
  - **Repo selector**: dropdown from GET /api/repos. Show green/red dot for TC index status, node count + last indexed underneath.
  - **Branch from**: dropdown, populated from GET /api/repos/{name}/branches, default 'main'
  - **Feature name**: text input
  - **Description**: textarea
  - **Additional context**: text input to add file paths, shown as removable pills
  - **Optional fields** (collapsible "Add more context" section):
    - Scope notes (textarea)
    - Architecture notes (textarea)
    - Constraints (textarea)
    - Testing notes (textarea)
  - **Submit button**: POST /api/tasks, redirect to /tasks/{id}
  - All optional fields stored in `optional_answers` JSON

### Task list

- `src/pages/TaskList.tsx`:
  - GET /api/tasks on mount
  - Table: feature name, repo, state badge, submitter, created time
  - State badges: submitted=gray, researching=amber, researched=blue, approved=green, rejected=red, failed=red
  - Click row → /tasks/{id}
  - Auto-refresh every 5s

### Task detail + review

- `src/pages/TaskDetail.tsx`:
  - GET /api/tasks/{id}
  - **Header**: feature name, repo, branch, state badge, submitter, timestamps
  - **State-dependent content**:
    - `researching`: loading spinner + "Analyzing codebase..."
    - `researched`: show research summary + Approve/Reject buttons (only for admins)
    - `approved`: show research with "Approved by {username}" badge
    - `rejected`: show research with "Rejected" badge
    - `failed`: show error message
  - Auto-refresh every 3s when state is `submitted` or `researching`

### Research view component

- `src/components/ResearchView.tsx`:
  - Takes research JSON as prop
  - Renders:
    - Summary paragraph
    - Affected code as a file list with change type badges (create=green, modify=amber, delete=red) and descriptions
    - Complexity card: score (big number), label badge, estimated effort, reasoning text
    - Metrics: files affected/created/modified, services affected, contract changes flag, new dependencies as pills, risk areas as a list
  - Approve button: POST /api/tasks/{id}/approve
  - Reject button: POST /api/tasks/{id}/reject (optional reason textarea)

### Navigation

- Top nav: Breakdown logo/name, "New request" link, "Tasks" link, username + role badge, logout

## Verify

```bash
cd frontend && npm run dev
# Open localhost:5173
# Login with username
# Submit a feature request — redirects to detail page
# See "Analyzing codebase..." spinner
# Research appears after 10-15s
# If admin: see Approve/Reject buttons
# If member: see research but no action buttons
# Click Approve — state changes to approved
# Go to /tasks — see all tasks with state badges
```

## Merge

```bash
cd ../breakdown
git merge feature/frontend
git worktree remove ../breakdown-frontend
```
