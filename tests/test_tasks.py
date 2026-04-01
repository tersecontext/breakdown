import asyncio
import json
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.auth import get_current_user, require_admin
from app.db import get_session
from app.models import User, Task, TaskLog


TASK_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()

member = User(id=USER_ID, username="kmcbeth", role="member")
admin_user = User(id=ADMIN_ID, username="admin", role="admin")


def make_task(state="submitted", research=None):
    task = MagicMock(spec=Task)
    task.id = TASK_ID
    task.feature_name = "ts-parser"
    task.description = "Add TypeScript support"
    task.repo = "tersecontext"
    task.branch_from = "main"
    task.state = state
    task.submitter_id = USER_ID
    task.approved_by_id = None
    task.approved_at = None
    task.source_channel = None
    task.slack_channel_id = None
    task.slack_thread_ts = None
    task.additional_context = []
    task.optional_answers = {}
    task.tc_context = None
    task.research = research
    task.error_message = None
    task.created_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    task.updated_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    task.logs = []
    task.submitter = member
    return task


def make_mock_session(task=None, user=None):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    result.scalar_one.return_value = task
    result.scalars.return_value.all.return_value = [task] if task else []
    session.execute.return_value = result
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def setup_auth(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user


def setup_session(session):
    async def override():
        yield session
    app.dependency_overrides[get_session] = override


@pytest.mark.asyncio
async def test_post_tasks_creates_task_and_returns_201():
    """POST /api/tasks creates a task with state=submitted and returns 201"""
    task = make_task()
    session = make_mock_session(task)
    setup_auth(member)
    setup_session(session)

    app.state.tc_client = AsyncMock()
    app.state.llm_client = AsyncMock()
    app.state.background_tasks = set()

    with patch("app.routes.tasks.asyncio.create_task"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/tasks",
                json={"feature_name": "ts-parser", "description": "Add TypeScript support", "repo": "tersecontext"},
                headers={"X-User": "kmcbeth"},
            )

    assert response.status_code == 201
    data = response.json()
    assert data["feature_name"] == "ts-parser"
    assert data["state"] == "submitted"


@pytest.mark.asyncio
async def test_get_tasks_returns_list():
    """GET /api/tasks returns a list of TaskListItem"""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(make_task(), "kmcbeth")]
    session.execute.return_value = result
    setup_auth(member)

    async def override():
        yield session
    app.dependency_overrides[get_session] = override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/tasks", headers={"X-User": "kmcbeth"})

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["feature_name"] == "ts-parser"
    assert data[0]["submitter_username"] == "kmcbeth"


@pytest.mark.asyncio
async def test_get_task_by_id_returns_full_task():
    """GET /api/tasks/{id} returns full TaskOut"""
    task = make_task()
    session = make_mock_session(task)
    setup_auth(member)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/tasks/{TASK_ID}", headers={"X-User": "kmcbeth"})

    assert response.status_code == 200
    assert response.json()["id"] == str(TASK_ID)


@pytest.mark.asyncio
async def test_get_task_by_id_returns_404_when_not_found():
    """GET /api/tasks/{id} returns 404 when task does not exist"""
    session = make_mock_session(None)
    setup_auth(member)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/tasks/{uuid.uuid4()}", headers={"X-User": "kmcbeth"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_task_sets_approved_state():
    """POST /api/tasks/{id}/approve sets state=approved and pushes to Redis"""
    task = make_task(state="researched", research={"summary": "test"})
    task.approved_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    app.state.redis = AsyncMock()
    app.state.tc_client = AsyncMock()
    app.state.llm_client = AsyncMock()
    app.state.background_tasks = set()

    with patch("app.routes.tasks.publish_approved_task", new_callable=AsyncMock) as mock_publish:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/tasks/{TASK_ID}/approve",
                headers={"X-User": "admin"},
            )

    assert response.status_code == 200
    assert task.state == "approved"
    mock_publish.assert_called_once()


@pytest.mark.asyncio
async def test_approve_task_returns_409_when_not_researched():
    """POST /api/tasks/{id}/approve returns 409 when task is not in state=researched"""
    task = make_task(state="submitted")
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/approve",
            headers={"X-User": "admin"},
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_task_returns_403_for_member():
    """POST /api/tasks/{id}/approve returns 403 when called by a non-admin"""
    from fastapi import HTTPException

    def raise_403():
        raise HTTPException(status_code=403, detail="Admin required")

    app.dependency_overrides[get_current_user] = lambda: member
    app.dependency_overrides[require_admin] = raise_403

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/approve",
            headers={"X-User": "kmcbeth"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_task_sets_rejected_state():
    """POST /api/tasks/{id}/reject sets state=rejected"""
    task = make_task(state="researched")
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/reject",
            json={"reason": "not a priority"},
            headers={"X-User": "admin"},
        )

    assert response.status_code == 200
    assert task.state == "rejected"


@pytest.mark.asyncio
async def test_reject_task_returns_409_when_not_researched():
    """POST /api/tasks/{id}/reject returns 409 when task is not in state=researched"""
    task = make_task(state="approved")
    session = make_mock_session(task)
    setup_auth(admin_user)
    setup_session(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/tasks/{TASK_ID}/reject",
            headers={"X-User": "admin"},
        )

    assert response.status_code == 409
