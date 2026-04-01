import uuid
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import User, Task, TaskLog
from app.token import create_access_token


def auth_header(user: User) -> dict:
    token = create_access_token(user.id, uuid.uuid4(), user.role)
    return {"Authorization": f"Bearer {token}"}


async def make_user(db_session, username="testuser", role="member"):
    user = User(username=username, role=role, password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


async def make_task(db_session, submitter, state="submitted", research=None):
    task = Task(
        feature_name="ts-parser",
        description="Add TypeScript support",
        repo="tersecontext",
        branch_from="main",
        submitter_id=submitter.id,
    )
    db_session.add(task)
    await db_session.flush()
    if state != "submitted" or research is not None:
        task.state = state
        if research is not None:
            task.research = research
        await db_session.flush()
    await db_session.refresh(task)
    return task


@pytest.mark.asyncio
async def test_post_tasks_creates_task_and_returns_201(app_client, db_session):
    from app.main import app as fastapi_app
    user = await make_user(db_session)
    fastapi_app.state.tc_client = AsyncMock()
    fastapi_app.state.llm_client = AsyncMock()
    fastapi_app.state.background_tasks = set()

    with patch("app.routes.tasks.asyncio.create_task") as mock_create_task:
        response = await app_client.post(
            "/api/tasks",
            json={"feature_name": "ts-parser", "description": "Add TypeScript support", "repo": "tersecontext"},
            headers=auth_header(user),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["feature_name"] == "ts-parser"
    assert data["state"] == "submitted"
    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_get_tasks_returns_list(app_client, db_session):
    user = await make_user(db_session)
    task = await make_task(db_session, user)
    response = await app_client.get("/api/tasks", headers=auth_header(user))
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    matching = [t for t in data if t["id"] == str(task.id)]
    assert len(matching) == 1
    assert matching[0]["feature_name"] == "ts-parser"
    assert matching[0]["submitter_username"] == "testuser"


@pytest.mark.asyncio
async def test_get_tasks_filters_by_state_and_repo(app_client, db_session):
    user = await make_user(db_session)
    await make_task(db_session, user, state="researched")
    response = await app_client.get(
        "/api/tasks",
        params={"state": "researched", "repo": "tersecontext"},
        headers=auth_header(user),
    )
    assert response.status_code == 200
    data = response.json()
    assert any(t["state"] == "researched" and t["repo"] == "tersecontext" for t in data)


@pytest.mark.asyncio
async def test_get_task_by_id_returns_full_task(app_client, db_session):
    user = await make_user(db_session)
    task = await make_task(db_session, user)
    response = await app_client.get(f"/api/tasks/{task.id}", headers=auth_header(user))
    assert response.status_code == 200
    assert response.json()["id"] == str(task.id)


@pytest.mark.asyncio
async def test_get_task_by_id_returns_404_when_not_found(app_client, db_session):
    user = await make_user(db_session)
    response = await app_client.get(f"/api/tasks/{uuid.uuid4()}", headers=auth_header(user))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_task_sets_approved_state(app_client, db_session):
    from app.main import app as fastapi_app
    admin = await make_user(db_session, "admin", role="admin")
    task = await make_task(db_session, admin, state="researched", research={"summary": "test"})

    fastapi_app.state.redis = AsyncMock()

    with patch("app.routes.tasks.publish_approved_task", new_callable=AsyncMock) as mock_publish:
        response = await app_client.post(
            f"/api/tasks/{task.id}/approve",
            headers=auth_header(admin),
        )

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    mock_publish.assert_called_once()


@pytest.mark.asyncio
async def test_approve_task_returns_409_when_not_researched(app_client, db_session):
    admin = await make_user(db_session, "admin2", role="admin")
    task = await make_task(db_session, admin, state="submitted")
    response = await app_client.post(f"/api/tasks/{task.id}/approve", headers=auth_header(admin))
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_task_returns_403_for_member(app_client, db_session):
    member = await make_user(db_session, "member2", role="member")
    admin = await make_user(db_session, "admin3", role="admin")
    task = await make_task(db_session, admin, state="researched", research={"summary": "test"})
    response = await app_client.post(f"/api/tasks/{task.id}/approve", headers=auth_header(member))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_task_sets_rejected_state(app_client, db_session):
    admin = await make_user(db_session, "admin4", role="admin")
    task = await make_task(db_session, admin, state="researched")
    response = await app_client.post(
        f"/api/tasks/{task.id}/reject",
        json={"reason": "not a priority"},
        headers=auth_header(admin),
    )
    assert response.status_code == 200
    assert response.json()["state"] == "rejected"


@pytest.mark.asyncio
async def test_reject_task_returns_409_when_not_researched(app_client, db_session):
    admin = await make_user(db_session, "admin5", role="admin")
    task = await make_task(db_session, admin, state="approved")
    response = await app_client.post(f"/api/tasks/{task.id}/reject", headers=auth_header(admin))
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_task_returns_404_when_not_found(app_client, db_session):
    admin = await make_user(db_session, "admin6", role="admin")
    response = await app_client.post(f"/api/tasks/{uuid.uuid4()}/approve", headers=auth_header(admin))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_task_returns_500_when_redis_fails(app_client, db_session):
    from app.main import app as fastapi_app
    admin = await make_user(db_session, "admin7", role="admin")
    task = await make_task(db_session, admin, state="researched", research={"summary": "test"})

    fastapi_app.state.redis = AsyncMock()

    with patch("app.routes.tasks.publish_approved_task", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = Exception("Redis connection refused")
        response = await app_client.post(
            f"/api/tasks/{task.id}/approve",
            headers=auth_header(admin),
        )

    assert response.status_code == 500
