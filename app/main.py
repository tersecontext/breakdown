import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.clients.anthropic import AnthropicClient
from app.clients.redis import RedisQueue
from app.clients.tersecontext import TerseContextClient
from app.config import settings
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
    app.state.tc_client = TerseContextClient(settings.tersecontext_url)
    app.state.llm_client = AnthropicClient(settings.anthropic_api_key, settings.default_model)
    app.state.redis = RedisQueue(settings.redis_url)
    app.state.background_tasks = set()  # holds references to prevent GC
    yield
    await app.state.tc_client.close()
    await app.state.redis.close()
    # AnthropicClient has no close() method
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
