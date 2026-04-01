import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tersecontext:localpassword@172.26.0.7/breakdown_test")
os.environ.setdefault("SOURCE_DIRS", "/tmp")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-minimum!")

TEST_DB_URL = os.environ["DATABASE_URL"]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_conn(db_engine):
    """One connection per test. Outer transaction is never committed — always rolled back."""
    async with db_engine.connect() as conn:
        await conn.begin()
        yield conn
        await conn.rollback()


@pytest_asyncio.fixture
async def db_session(db_conn):
    """Session bound to the test connection. commit() is overridden to flush() so
    route handlers can call commit() without destroying the outer transaction."""
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    session = factory()
    session.commit = session.flush
    yield session
    await session.close()


@pytest_asyncio.fixture
async def app_client(db_session):
    """AsyncClient with get_session overridden to use the transactional test session."""
    from app.main import app
    from app.db import get_session

    async def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def mock_tc():
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


@pytest_asyncio.fixture
async def mock_anthropic():
    """AnthropicClient mock that returns canned research JSON."""
    llm = AsyncMock()
    response = MagicMock()
    response.content = json.dumps(CANNED_RESEARCH)
    llm.chat.return_value = response
    return llm
