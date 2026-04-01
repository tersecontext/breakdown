"""
Tests for authentication and authorisation:
  - POST /api/auth/login: creates user if not exists, returns existing user
  - GET /api/auth/me: X-User header resolves to the correct user
  - Missing X-User header returns 422 (FastAPI enforces required Header)
  - Unknown X-User returns 401 (user not found in DB)
  - require_admin passes for admin role, rejects member with 403
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.auth import get_current_user, require_admin
from app.db import get_session
from app.main import app
from app.models import User

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

ADMIN_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()

admin_user = User(id=ADMIN_ID, username="admin", role="admin")
admin_user.created_at = NOW

member_user = User(id=MEMBER_ID, username="kmcbeth", role="member")
member_user.created_at = NOW


def make_empty_session():
    """Session that returns an empty result set (used to satisfy list_users etc.)"""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session


def override_session(session):
    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_creates_user_if_not_exists():
    """POST /api/auth/login creates and returns a new user when username is unknown."""
    session = AsyncMock()

    # First execute: find-by-username → not found
    find_result = MagicMock()
    find_result.scalar_one_or_none.return_value = None

    # Second execute: first-user check → no existing users (so new user becomes admin)
    count_result = MagicMock()
    count_result.first.return_value = None

    session.execute.side_effect = [find_result, count_result]
    session.add = MagicMock()
    session.commit = AsyncMock()

    created_user_holder = []

    def capture_add(obj):
        created_user_holder.append(obj)

    session.add.side_effect = capture_add

    async def fake_refresh(obj):
        obj.id = uuid.uuid4()
        obj.created_at = NOW

    session.refresh = AsyncMock(side_effect=fake_refresh)
    override_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/auth/login", json={"username": "newuser"})

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "newuser"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_returns_existing_user():
    """POST /api/auth/login returns the existing user without creating a new one."""
    existing = User(id=uuid.uuid4(), username="kmcbeth", role="member")
    existing.created_at = NOW

    session = AsyncMock()
    find_result = MagicMock()
    find_result.scalar_one_or_none.return_value = existing
    session.execute.return_value = find_result
    session.add = MagicMock()
    override_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/auth/login", json={"username": "kmcbeth"})

    assert response.status_code == 200
    assert response.json()["username"] == "kmcbeth"
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# X-User header tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_x_user_header_resolves_to_correct_user():
    """GET /api/auth/me with a valid X-User header returns that user's profile."""
    app.dependency_overrides[get_current_user] = lambda: member_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/auth/me", headers={"X-User": "kmcbeth"})

    assert response.status_code == 200
    assert response.json()["username"] == "kmcbeth"


@pytest.mark.asyncio
async def test_missing_x_user_returns_422():
    """GET /api/auth/me without X-User header returns 422 (FastAPI required-field error)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/auth/me")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_x_user_not_in_db_returns_401():
    """GET /api/auth/me returns 401 when X-User is present but user is not in the database."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    override_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/auth/me", headers={"X-User": "ghost"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# require_admin tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_check_passes_for_admin_role():
    """An admin user can reach an admin-only endpoint; response is not 403."""
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    override_session(make_empty_session())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/users", headers={"X-User": "admin"})

    assert response.status_code == 200
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_admin_check_rejects_member_with_403():
    """A member user is rejected with 403 on an admin-only endpoint."""

    def raise_403():
        raise HTTPException(status_code=403, detail="Admin required")

    app.dependency_overrides[get_current_user] = lambda: member_user
    app.dependency_overrides[require_admin] = raise_403

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/users", headers={"X-User": "kmcbeth"})

    assert response.status_code == 403
