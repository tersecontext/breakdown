import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tersecontext:localpassword@172.26.0.7/breakdown_test")
os.environ.setdefault("SOURCE_DIRS", "/tmp")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

# Patch AsyncMock so that when no explicit side_effect/return_value is set,
# the return value of awaitable methods is a MagicMock (not AsyncMock).
# This ensures `result.scalar_one_or_none()` returns None by default,
# matching SQLAlchemy session semantics in tests.
_original_get_child_mock = AsyncMock._get_child_mock


def _patched_get_child_mock(self, **kw):
    if kw.get("_new_name") == "()":
        rv = MagicMock(**kw)
        rv.scalar_one_or_none.return_value = None
        rv.scalars.return_value.all.return_value = []
        return rv
    return _original_get_child_mock(self, **kw)


AsyncMock._get_child_mock = _patched_get_child_mock

TEST_DB_URL = os.environ["DATABASE_URL"]

# Create tables once at module load time using the sync asyncio.run approach
# so we don't fight pytest-asyncio event loop scoping.
import asyncio as _asyncio


def _ensure_tables():
    from app.models import Base

    engine = create_async_engine(TEST_DB_URL, echo=False)

    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    _asyncio.run(_run())


try:
    _ensure_tables()
except Exception:
    pass  # If DB is unavailable, model tests will fail clearly on connect


@pytest.fixture
async def db_session():
    """Yield an async session for one test; commit is the test's responsibility."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client():
    """httpx AsyncClient pointed at the FastAPI app via ASGI transport."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_tc():
    """TerseContextClient mock that returns a canned context string."""
    tc = AsyncMock()
    tc.query.return_value = "canned context: the parser lives in parser.py"
    tc.health.return_value = {"status": "ok", "node_count": 10, "last_indexed": "2026-01-01"}
    return tc


CANNED_RESEARCH = {
    "summary": "Add TypeScript parsing to the existing parser module.",
    "affected_code": [
        {"file": "parser.py", "change_type": "modify", "description": "add ts token handling"}
    ],
    "complexity": {
        "score": 2,
        "label": "low",
        "estimated_effort": "1-2 hours",
        "reasoning": "isolated change to one module",
    },
    "metrics": {
        "files_affected": 1,
        "files_created": 0,
        "files_modified": 1,
        "services_affected": 0,
        "contract_changes": False,
        "new_dependencies": [],
        "risk_areas": [],
    },
}


@pytest.fixture
def mock_anthropic():
    """AnthropicClient mock that returns canned research JSON."""
    llm = AsyncMock()
    response = MagicMock()
    response.content = json.dumps(CANNED_RESEARCH)
    llm.chat.return_value = response
    return llm
