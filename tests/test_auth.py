"""
Auth tests for the JWT-based authentication system.
"""
import pytest
import uuid
from app.models import User
from app.token import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def make_user(db_session, username="testuser", role="member", password_hash=None):
    import bcrypt
    ph = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode() if password_hash is None else password_hash
    user = User(username=username, role=role, password_hash=ph)
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


def bearer(user: User, session_id=None) -> str:
    sid = session_id or uuid.uuid4()
    return create_access_token(user.id, sid, user.role)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_success_returns_access_token(app_client, db_session):
    await make_user(db_session, "alice")
    r = await app_client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["user"]["username"] == "alice"


async def test_login_wrong_password_returns_401(app_client, db_session):
    await make_user(db_session, "bob")
    r = await app_client.post("/api/auth/login", json={"username": "bob", "password": "wrong"})
    assert r.status_code == 401


async def test_login_unknown_user_returns_401(app_client, db_session):
    r = await app_client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


async def test_login_empty_password_rejected(app_client, db_session):
    r = await app_client.post("/api/auth/login", json={"username": "alice", "password": ""})
    assert r.status_code == 422


async def test_login_null_hash_sets_password_on_first_login(app_client, db_session):
    """Existing users with no password can log in once to set it."""
    user = User(username="legacy", role="member", password_hash=None)
    db_session.add(user)
    await db_session.flush()

    r = await app_client.post("/api/auth/login", json={"username": "legacy", "password": "newpass"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

async def test_me_with_valid_token(app_client, db_session):
    user = await make_user(db_session, "carol")
    r = await app_client.get("/api/auth/me", headers={"Authorization": f"Bearer {bearer(user)}"})
    assert r.status_code == 200
    assert r.json()["username"] == "carol"


async def test_me_missing_auth_header_returns_422(app_client):
    r = await app_client.get("/api/auth/me")
    assert r.status_code == 422


async def test_me_invalid_token_returns_401(app_client):
    r = await app_client.get("/api/auth/me", headers={"Authorization": "Bearer notavalidtoken"})
    assert r.status_code == 401


async def test_me_expired_token_returns_401(app_client, db_session):
    import app.token as token_module
    original = token_module.settings.access_token_ttl
    token_module.settings.access_token_ttl = -1
    user = await make_user(db_session, "dave")
    tok = bearer(user)
    token_module.settings.access_token_ttl = original
    r = await app_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------

async def test_admin_endpoint_accessible_by_admin(app_client, db_session):
    admin = await make_user(db_session, "admin2", role="admin")
    r = await app_client.get("/api/users", headers={"Authorization": f"Bearer {bearer(admin)}"})
    assert r.status_code == 200


async def test_admin_endpoint_rejected_for_member(app_client, db_session):
    member = await make_user(db_session, "member2", role="member")
    r = await app_client.get("/api/users", headers={"Authorization": f"Bearer {bearer(member)}"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Refresh, logout, set-password
# ---------------------------------------------------------------------------

async def test_refresh_returns_new_access_token(app_client, db_session):
    """POST /api/auth/refresh with a valid cookie issues a new access token."""
    await make_user(db_session, "refresher")
    # Login to get a refresh cookie
    login_r = await app_client.post("/api/auth/login", json={"username": "refresher", "password": "password123"})
    assert login_r.status_code == 200
    # Extract the refresh token from Set-Cookie header directly (httpx won't send
    # secure cookies back over http://test, so we pass it manually)
    set_cookie = login_r.headers.get("set-cookie", "")
    raw_token = None
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith("refresh_token="):
            raw_token = part[len("refresh_token="):]
            break
    assert raw_token is not None, "Login did not set refresh_token cookie"
    r = await app_client.post("/api/auth/refresh", cookies={"refresh_token": raw_token})
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_refresh_without_cookie_returns_401(app_client):
    r = await app_client.post("/api/auth/refresh")
    assert r.status_code == 401


async def test_logout_revokes_session(app_client, db_session):
    """After logout, the refresh token cookie should no longer work."""
    await make_user(db_session, "logoutuser")
    login_r = await app_client.post("/api/auth/login", json={"username": "logoutuser", "password": "password123"})
    assert login_r.status_code == 200
    access_token = login_r.json()["access_token"]
    # Extract refresh token for later use
    set_cookie = login_r.headers.get("set-cookie", "")
    raw_token = None
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith("refresh_token="):
            raw_token = part[len("refresh_token="):]
            break
    assert raw_token is not None

    logout_r = await app_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_r.status_code == 204

    # Refresh should now fail because the session is revoked
    r = await app_client.post("/api/auth/refresh", cookies={"refresh_token": raw_token})
    assert r.status_code == 401


async def test_set_password_updates_and_issues_new_token(app_client, db_session):
    await make_user(db_session, "changepw")
    login_r = await app_client.post("/api/auth/login", json={"username": "changepw", "password": "password123"})
    token = login_r.json()["access_token"]

    r = await app_client.post(
        "/api/auth/set-password",
        json={"new_password": "newpassword456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()

    # Old password should no longer work
    r2 = await app_client.post("/api/auth/login", json={"username": "changepw", "password": "password123"})
    assert r2.status_code == 401

    # New password should work
    r3 = await app_client.post("/api/auth/login", json={"username": "changepw", "password": "newpassword456"})
    assert r3.status_code == 200
