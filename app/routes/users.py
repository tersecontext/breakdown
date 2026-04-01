import uuid as _uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_admin
from app.db import get_session
from app.models import Session, User
from app.schemas import (
    LoginRequest,
    RefreshResponse,
    SetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.token import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.config import settings

router = APIRouter()


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=raw_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.refresh_token_ttl,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie("refresh_token", path="/api/auth")


async def _create_session(
    user: User, db: AsyncSession
) -> tuple[str, str]:
    """Create a DB session row, clean up expired sessions. Returns (access_token, raw_refresh_token)."""
    raw_refresh, refresh_hash = generate_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl)

    new_session = Session(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )
    db.add(new_session)
    await db.flush()  # get session.id before creating access token

    access_token = create_access_token(user.id, new_session.id, user.role)

    # Clean up expired sessions for this user opportunistically
    await db.execute(
        Session.__table__.delete().where(
            Session.user_id == user.id,
            Session.expires_at < datetime.now(timezone.utc),
            Session.id != new_session.id,
        )
    )
    return access_token, raw_refresh


@router.post("/api/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.password_hash is None:
        # First login — set the password
        user.password_hash = bcrypt.hashpw(
            body.password.encode(), bcrypt.gensalt()
        ).decode()
        db.add(user)
    else:
        if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
            raise HTTPException(status_code=401, detail="Invalid password")

    access_token, raw_refresh = await _create_session(user, db)
    await db.flush()
    _set_refresh_cookie(response, raw_refresh)

    return TokenResponse(
        access_token=access_token,
        user=UserOut.model_validate(user),
    )


@router.post("/api/auth/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_session),
    refresh_token: str | None = Cookie(default=None),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    token_hash = hash_refresh_token(refresh_token)
    result = await db.execute(
        select(Session).where(Session.token_hash == token_hash)
    )
    session_row = result.scalar_one_or_none()

    if session_row is None or session_row.revoked:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if session_row.expires_at.astimezone(timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    # Rotate: revoke old, create new — all in the same flush
    session_row.revoked = True
    db.add(session_row)

    user_result = await db.execute(select(User).where(User.id == session_row.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    access_token, raw_refresh = await _create_session(user, db)
    await db.flush()
    _set_refresh_cookie(response, raw_refresh)

    return RefreshResponse(access_token=access_token)


@router.post("/api/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = auth[7:]
    payload = decode_access_token(token)
    jti = payload["jti"]

    await db.execute(
        update(Session)
        .where(Session.id == _uuid.UUID(jti))
        .values(revoked=True)
    )
    await db.flush()
    _clear_refresh_cookie(response)


@router.post("/api/auth/set-password", response_model=TokenResponse)
async def set_password(
    body: SetPasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    user.password_hash = bcrypt.hashpw(
        body.new_password.encode(), bcrypt.gensalt()
    ).decode()
    db.add(user)

    # Revoke all existing sessions for this user
    await db.execute(
        update(Session).where(Session.user_id == user.id).values(revoked=True)
    )
    await db.flush()

    # Issue new session
    access_token, raw_refresh = await _create_session(user, db)
    await db.flush()
    _set_refresh_cookie(response, raw_refresh)

    return TokenResponse(
        access_token=access_token,
        user=UserOut.model_validate(user),
    )


@router.get("/api/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/api/users", response_model=UserOut)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(username=body.username, role=body.role)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/api/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User))
    return result.scalars().all()


@router.patch("/api/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user id")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = body.role
    await db.flush()
    await db.refresh(user)
    return user
