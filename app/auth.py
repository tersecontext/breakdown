from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User


async def get_current_user(
    x_user: str = Header(..., alias="X-User"),
    session: AsyncSession = Depends(get_session),
) -> User:
    result = await session.execute(select(User).where(User.username == x_user))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user
