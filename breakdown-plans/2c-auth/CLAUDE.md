# Subtask 2c: Auth + users API

**Layer:** 2 (parallel — run alongside 2a and 2b after subtask 1 merges)
**Branch:** `feature/auth`
**Worktree:** `../breakdown-auth`

## Setup

```bash
cd breakdown
git worktree add -b feature/auth ../breakdown-auth
cp subtasks/2c-auth/CLAUDE.md ../breakdown-auth/SUBTASK.md
cd ../breakdown-auth
```

## What to build

Simple username-based auth with admin/member roles. No passwords for v1.

- Create `app/auth.py`:
  - `async def get_current_user(request: Request, session: AsyncSession) -> User`
    - Read username from `X-User` header (simple for v1)
    - Look up user in database
    - Raise 401 if not found
  - `async def require_admin(user: User) -> User`
    - Check user.role == 'admin'
    - Raise 403 if not admin
  - These are FastAPI dependencies that can be injected into route handlers

- Create `app/routes/users.py`:
  - `POST /api/users` — admin only. Create user with username and role. Return user object.
  - `GET /api/users` — admin only. List all users.
  - `PATCH /api/users/{id}` — admin only. Update role.
  - `POST /api/auth/login` — accepts `{"username": "..."}`, returns user object with role. Creates user as member if doesn't exist (auto-registration).
  - `GET /api/auth/me` — returns current user from X-User header

- Register users router in `app/main.py`

- Create a seed script or startup logic: if no users exist, create a default admin user (username from env var or "admin")

## Verify

```bash
uvicorn app.main:app --reload --port 8000

# Auto-register:
curl -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"kmcbeth"}'
# expect: user object with role='member' (or 'admin' if first user)

# Check current user:
curl http://localhost:8000/api/auth/me -H 'X-User: kmcbeth'
# expect: user object

# Admin creates another user:
curl -X POST http://localhost:8000/api/users \
  -H 'Content-Type: application/json' \
  -H 'X-User: admin' \
  -d '{"username":"teammate","role":"member"}'

# Member cannot create users:
curl -X POST http://localhost:8000/api/users \
  -H 'Content-Type: application/json' \
  -H 'X-User: teammate' \
  -d '{"username":"hacker","role":"admin"}'
# expect: 403
```

## Merge

```bash
cd ../breakdown
git merge feature/auth
git worktree remove ../breakdown-auth
```
