import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.db import AsyncSessionLocal, engine
from app.models import User
from app.routes.repos import router as repos_router
from app.routes.tasks import router as tasks_router
from app.routes.users import router as users_router


async def seed_admin() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        if result.first() is None:
            username = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
            session.add(User(username=username, role="admin"))
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_admin()
    yield
    await engine.dispose()


app = FastAPI(title="Breakdown", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router)


app.include_router(repos_router)


app.include_router(tasks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
