import asyncio
import logging
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
from app.engine.fracture_consumer import consume_fracture_results
from app.models import User
from app.routes.repos import router as repos_router
from app.routes.tasks import router as tasks_router
from app.routes.users import router as users_router

logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    proc = await asyncio.create_subprocess_exec("alembic", "upgrade", "head")
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed with code {proc.returncode}")


async def seed_admin() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        if result.first() is None:
            username = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
            session.add(User(username=username, role="admin"))
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    await seed_admin()
    app.state.tc_client = TerseContextClient(settings.tersecontext_url)
    app.state.llm_client = AnthropicClient(settings.anthropic_api_key, settings.default_model)
    app.state.redis = RedisQueue(settings.redis_url)
    app.state.background_tasks = set()  # holds references to prevent GC

    # Persistent Slack web client — used by fracture consumer for error notifications.
    # Also used below for channel-id lookup (replaces the previous ephemeral client).
    app.state.slack_web_client = None
    if settings.slack_bot_token:
        from slack_sdk.web.async_client import AsyncWebClient
        app.state.slack_web_client = AsyncWebClient(token=settings.slack_bot_token)

    slack_bot = None
    if settings.slack_bot_token and settings.slack_app_token:
        try:
            from app.clients.slack_bot import SlackBot

            channel_id = None
            try:
                cursor = None
                while channel_id is None:
                    resp = await app.state.slack_web_client.conversations_list(
                        exclude_archived=True, limit=200, cursor=cursor
                    )
                    for ch in resp["channels"]:
                        if ch["name"] == settings.slack_channel:
                            channel_id = ch["id"]
                            break
                    cursor = resp.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
            except Exception:
                logger.exception("Failed to look up Slack channel ID")

            if channel_id is None:
                logger.warning(
                    "Slack channel '%s' not found; bot will not start", settings.slack_channel
                )
            else:
                slack_bot = SlackBot(app.state, channel_id=channel_id)
                await slack_bot.start()
                logger.info("Slack bot started (channel=%s)", channel_id)
        except Exception:
            logger.exception("Failed to start Slack bot")

    # Fracture results consumer — runs for the lifetime of the process.
    consumer_task = asyncio.create_task(consume_fracture_results(app.state))

    yield

    # ── Shutdown ────────────────────────────────────────────────────────────
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    if slack_bot is not None:
        await slack_bot.stop()
    await app.state.tc_client.close()
    await app.state.redis.close()
    if app.state.slack_web_client is not None:
        await app.state.slack_web_client.session.close()
    await engine.dispose()


app = FastAPI(title="Breakdown", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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
