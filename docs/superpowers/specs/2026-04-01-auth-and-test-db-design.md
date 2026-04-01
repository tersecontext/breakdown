# Auth Hardening + Test DB Isolation — Design Spec

**Date:** 2026-04-01
**Status:** Approved
**Scope:** Two high-priority fixes — (1) replace header-based auth with JWT + refresh tokens + passwords, (2) replace mock-based DB tests with transaction-scoped real DB isolation.

---

## 1. Authentication Hardening

### Problem

`auth.py` trusts the `X-User: <username>` request header at face value. Any caller can impersonate any user with no credential. The app may be internet-exposed.

### Solution Overview

- Add `bcrypt` password hashing to `User`
- Add a `sessions` table for revocable refresh tokens
- Issue short-lived JWTs (HS256, 15-min) as access tokens; `jti` (token ID) included in payload to support single-session logout
- Issue 7-day refresh tokens (stored as SHA-256 hash in DB), rotated on every use atomically within a single DB transaction
- **Token storage**: access token in-memory only (React module-level variable, not `localStorage`); refresh token in an `HttpOnly; Secure; SameSite=Strict` cookie set by the server — never exposed to JavaScript. This prevents XSS from stealing tokens.
- Frontend sends `Authorization: Bearer <access_token>` for all API calls; on 401 the frontend calls `/api/auth/refresh` (the browser automatically sends the cookie), gets a new access token in the response body, and retries.
- Replace `X-User` header dependency everywhere with JWT verification
- Add `CORS_ORIGINS` setting; remove wildcard `allow_origins=["*"]`

### Data Model

#### `users` table — new column
```
password_hash  TEXT NULL
```
NULL means the user was created before this change and must set a password on first login.

#### `sessions` table — new
```
id          UUID        PRIMARY KEY  DEFAULT gen_random_uuid()
user_id     UUID        NOT NULL     REFERENCES users(id) ON DELETE CASCADE
token_hash  TEXT        NOT NULL     UNIQUE   -- SHA-256 hex of raw refresh token
expires_at  TIMESTAMP   NOT NULL
revoked     BOOLEAN     NOT NULL     DEFAULT false
created_at  TIMESTAMP   NOT NULL     DEFAULT now()
```

Indexes:
- `sessions(token_hash)` — fast lookup on every refresh
- `sessions(user_id)` — fast cascade revocation
- `sessions(expires_at)` — efficient purge of expired rows

#### Session cleanup strategy

Expired sessions are deleted opportunistically on login: after issuing a new session, delete all rows for that user where `expires_at < now()`. This bounds table growth without needing a cron job.

### Settings

```python
SECRET_KEY: str                   # Required. Min 32 chars. App fails to start if absent.
ACCESS_TOKEN_TTL: int = 900       # seconds (15 min)
REFRESH_TOKEN_TTL: int = 604800   # seconds (7 days)
CORS_ORIGINS: list[str] = []      # e.g. ["http://localhost:5173", "https://breakdown.example.com"]
JWT_ALGORITHM: str = "HS256"      # constant, not runtime-configurable; exposed for clarity
```

`CORS_ORIGINS` replaces `allow_origins=["*"]` in `main.py`. `allow_credentials` must be `True` for the cookie to be sent.

### Pydantic Schemas (new/updated in `schemas.py`)

```python
class LoginRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=1)   # non-empty enforced at schema level

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    # refresh_token is NOT in the response body — it is set as an HttpOnly cookie

class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class SetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=1)
```

### API Changes

#### `POST /api/auth/login`
- **Before:** `{username}` → auto-creates user, returns user record
- **After:** `{username, password}` (both non-empty, enforced by Pydantic schema)
- If user not found → 404
- If `password_hash` is NULL (existing user, first login): hash and store the supplied password, proceed normally
- If `password_hash` is set: verify with bcrypt, return 401 on mismatch
- Creates a `Session` row (SHA-256 hash of new refresh token). Deletes expired sessions for this user in the same transaction.
- Returns `TokenResponse` in body + sets `HttpOnly; Secure; SameSite=Strict` cookie named `refresh_token`

#### `POST /api/auth/refresh` — new
- No body. Browser sends the `refresh_token` cookie automatically.
- Server reads cookie value, computes SHA-256 hash, looks up in `sessions`
- Checks `expires_at` and `revoked`; returns 401 if invalid
- **Atomically** in a single DB transaction: mark old session `revoked = true`, insert new session row, delete expired sessions for this user
- Returns `RefreshResponse` in body + sets new `refresh_token` cookie

#### `POST /api/auth/logout` — new
- Requires valid JWT
- Revokes **only the current session** (identified by `jti` claim in JWT which matches session ID)
- Clears the `refresh_token` cookie (set-cookie with max-age=0)
- Returns 204

#### `POST /api/auth/set-password` — new
- Requires valid JWT
- Body: `{new_password}` (non-empty)
- Updates `password_hash` for the authenticated user
- **Revokes all active sessions** for the user (set `revoked = true` where `user_id = ?`)
- Returns 200 with fresh `TokenResponse` + new `refresh_token` cookie so the user remains logged in

#### `GET /api/auth/me`
- Same behavior (return user profile); now authenticates via JWT instead of X-User header

#### All other endpoints
- Replace `get_current_user` X-User header dependency with JWT Bearer verification
- `get_current_user` verifies JWT signature + expiry, extracts `sub` (user_id), loads `User` from DB (role is read from DB, not JWT, so live role changes take effect immediately)
- `require_admin` unchanged in signature, still depends on `get_current_user`

### `auth.py` — new shape

```python
ALGORITHM = "HS256"

async def get_current_user(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session),
) -> User:
    # 1. Parse "Bearer <token>"; raise 401 on missing/malformed header
    # 2. Verify JWT: PyJWT decode with SECRET_KEY, ALGORITHM, options={"require": ["exp", "sub", "jti"]}
    # 3. Extract sub (user_id UUID)
    # 4. Load User from DB; raise 401 if not found
    ...
```

`get_current_user` returns the `User` ORM object. For the logout endpoint, which needs to revoke the specific session identified by `jti`, the route handler re-decodes the token directly (it already has the raw `Authorization` header value) to extract `jti` — or uses a thin `get_token_payload` dependency that returns the decoded dict alongside the user. Either approach is acceptable; the implementation should pick one and be consistent.

JWT payload structure:
```json
{"sub": "<user_id>", "jti": "<session_id>", "role": "<role>", "exp": <unix_ts>}
```

### CORS Update (`main.py`)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Migration Path for Existing Users

- `password_hash` column is nullable; existing rows get NULL after migration
- The seeded `admin` user (created by `seed_admin` on first startup) also has `password_hash = NULL`
- `seed_admin` runs only when there are zero users — this is safe; the NULL-password first-login policy applies
- On first login with a NULL-hash account: the supplied password is hashed and stored; the user is logged in normally. No separate set-password step required.
- Empty password rejected at schema level (`min_length=1`), so `{"password": ""}` never reaches route logic.

### Dependencies to Add

```
bcrypt
PyJWT>=2.8.0
```

`python-jose` is **not** used — it is unmaintained and has published CVEs. `PyJWT` is the actively maintained standard.

### Frontend Changes

#### `api.ts`
- Module-level `let accessToken: string | null = null` — never written to `localStorage`
- `setAccessToken(token)` / `getAccessToken()` helpers
- All requests: `Authorization: Bearer ${accessToken}`
- Interceptor: on 401, call `/api/auth/refresh` (no body; cookie sent automatically). On success, update `accessToken` and retry original request. On failure, redirect to `/login`.
- Login: store access token in memory; refresh token is in cookie (no JS access needed)
- Logout: call `/api/auth/logout`, clear `accessToken`

#### `frontend/src/pages/Login.tsx`
- Add password `<input type="password">` field
- On submit: `POST /api/auth/login` with `{username, password}`
- Store returned `access_token` in memory; no localStorage writes for tokens

#### `frontend/src/App.tsx`
- `RequireAuth` guard: check in-memory `accessToken` (or re-attempt `/api/auth/refresh` on page load to restore session from cookie) instead of checking `localStorage.getItem('username')`

#### Note on `test_auth.py`
Existing tests `test_missing_x_user_returns_422` and `test_x_user_header_resolves_to_correct_user` test the mechanism being replaced, not just behavior. They must be **rewritten** with JWT-based equivalents (e.g., test missing Authorization header returns 401, test valid JWT resolves to correct user, test expired JWT returns 401).

---

## 2. Test Database Isolation

### Problem

`conftest.py` monkey-patches `AsyncMock._get_child_mock` to simulate SQLAlchemy session behavior. SQL constraint violations, ORM relationship loading bugs, and migration issues are invisible in tests.

### Solution

Transaction-scoped test isolation using the real test PostgreSQL database. Each test runs inside a nested transaction (SAVEPOINT) that is rolled back on teardown — route handlers can call `session.commit()` freely (commits only to the SAVEPOINT, not to the outer transaction).

### Fixture Hierarchy

```
db_engine  (session scope)   — one AsyncEngine for the whole pytest run
    └─ db_conn  (function scope)  — one connection, outer BEGIN + SAVEPOINT per test
           └─ db_session  (function scope)  — AsyncSession bound to db_conn
           └─ app_client  (function scope)  — AsyncClient with get_session overridden
```

### Correct SQLAlchemy 2.0 Async Pattern

`AsyncSession(bind=conn)` was **removed in SQLAlchemy 2.0**. The correct pattern is:

```python
@pytest.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()

@pytest.fixture
async def db_conn(db_engine):
    async with db_engine.connect() as conn:
        await conn.begin()            # outer transaction — never committed
        yield conn
        await conn.rollback()         # always rolls back after test

@pytest.fixture
async def db_session(db_conn):
    # Use async_sessionmaker bound to the connection, not the engine
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        yield session
```

### Handling Explicit `session.commit()` in Route Handlers

Routes call `await session.commit()` directly (e.g., `tasks.py`, `users.py`). A plain outer `BEGIN` + `ROLLBACK` would be destroyed by any real `COMMIT` issued by a route handler.

**Chosen approach: override `commit` to `flush` on the test session instance.** The session flushes (makes writes visible within the open transaction) but never issues a real `COMMIT` to the DB — so the outer `conn.rollback()` on teardown rolls everything back cleanly. Test assertions run after the route returns, so they see all flushed data.

```python
@pytest.fixture
async def db_session(db_conn):
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        # Make commit() a flush() so routes can call it without breaking isolation
        session.commit = session.flush
        yield session
```

### `conftest.py` Changes

- **Remove** `AsyncMock._get_child_mock` patch from global scope
- **Remove** `_ensure_tables()` call at module load (test DB is migrated via `alembic upgrade head` before running tests; document this in `README.md`)
- Add `db_engine`, `db_conn`, `db_session` fixtures as above
- Add `app_client` fixture:

```python
@pytest.fixture
async def app_client(db_session):
    from app.main import app
    from app.db import get_session

    async def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
```

- Keep `mock_tc` and `mock_anthropic` fixtures unchanged
- **Remove** the old `client` fixture; migrate all tests to `app_client`. There is no separate mock-session fixture tier — `mock_tc` and `mock_anthropic` are injected via `app.state` overrides in `app_client` for tests that need them.
- Add to `[tool.pytest.ini_options]` in `pyproject.toml`:
  ```toml
  asyncio_default_fixture_loop_scope = "session"
  ```
  This prevents a `ScopeMismatch` error for the session-scoped `db_engine` async fixture with pytest-asyncio >= 0.23.

### Test Migration

Two patterns exist in the current test suite that both need migration:

**Pattern A — tests using the `client` fixture** (e.g., `test_auth.py`, `test_repos.py`): replace `client` with `app_client`; remove any manual `AsyncMock` session setup passed via `app.dependency_overrides`.

**Pattern B — tests that construct their own `AsyncClient` inline with `AsyncMock` sessions** (e.g., `test_tasks.py`, `test_main.py`): these do not use `client` at all but still use `AsyncMock` for the DB session. Migrate these to `app_client` with real DB operations (insert real rows using `db_session` in the test body, assert against real DB state).

- Tests for `test_auth.py` X-User mechanism → rewrite for JWT (see auth section)
- DB setup in individual tests (`session.add(User(...)); await session.commit()`) continues to work — `commit` flushes, data is visible within the test transaction, rolled back at teardown

### Prerequisite

Add to `README.md` (Local Development section):
```bash
# Before running tests, migrate the test database:
DATABASE_URL=postgresql+asyncpg://tersecontext:localpassword@172.26.0.7/breakdown_test \
  alembic upgrade head
```

---

## 3. Out of Scope

- OAuth / external identity providers
- Email verification
- Password complexity requirements beyond non-empty (`min_length=1`)
- Rate limiting on login endpoint
- HTTPS termination (handled at reverse proxy)

---

## Implementation Order

1. Alembic migrations: add `password_hash` to `users`; create `sessions` table with all three indexes
2. `app/config.py` — add `SECRET_KEY` (required), `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL`, `CORS_ORIGINS`
3. `app/models.py` — add `Session` model
4. `app/schemas.py` — update `LoginRequest`, add `TokenResponse`, `RefreshResponse`, `SetPasswordRequest`
5. `app/auth.py` — rewrite around JWT Bearer verification; add `create_access_token` helper
6. `app/routes/users.py` — rewrite login (bcrypt + cookie), add `/refresh`, `/logout`, `/set-password`
7. `app/main.py` — update CORS middleware to use `settings.cors_origins`
8. All other routes — no change needed (they depend on `get_current_user` which is already updated in step 5)
9. `frontend/src/api.ts` — in-memory token, Bearer header, refresh interceptor
10. `frontend/src/pages/Login.tsx` — add password field
11. `frontend/src/App.tsx` — update `RequireAuth` guard
12. `tests/conftest.py` — transaction-scoped fixtures; remove global AsyncMock patch; add `asyncio_default_fixture_loop_scope = "session"` to `[tool.pytest.ini_options]` in `pyproject.toml`
13. `tests/test_auth.py` — rewrite X-User tests as JWT tests
14. All other test files — migrate Pattern A tests (`client` → `app_client`) and Pattern B tests (inline `AsyncMock` → `app_client` with real DB rows)
15. `README.md` — document test DB migration prerequisite and new auth flow
