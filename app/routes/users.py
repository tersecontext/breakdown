from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_admin
from app.db import get_session
from app.models import User
from app.schemas import LoginRequest, UserCreate, UserOut, UserUpdate

router = APIRouter()


@router.post("/api/auth/login", response_model=UserOut)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user is None:
        # Check if this is the first user — make them admin
        count_result = await session.execute(select(User))
        first_user = count_result.first() is None
        user = User(username=body.username, role="admin" if first_user else "member")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


@router.get("/api/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/api/users", response_model=UserOut)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(username=body.username, role=body.role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/api/users", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    result = await session.execute(select(User))
    return result.scalars().all()


@router.patch("/api/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    import uuid as _uuid
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user id")
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = body.role
    await session.commit()
    await session.refresh(user)
    return user
