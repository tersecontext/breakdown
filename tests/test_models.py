"""
Integration tests for SQLAlchemy models.
Requires a running PostgreSQL instance with the breakdown_test database.
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Task, TaskLog, User


@pytest.mark.asyncio
async def test_create_user(db_session):
    """Creating a User persists id, username, role, and created_at."""
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", role="member")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.id is not None
    assert user.username.startswith("u-")
    assert user.role == "member"
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_create_task_with_user_fk(db_session):
    """Creating a Task with submitter_id FK links correctly; default state is 'submitted'."""
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", role="member")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    task = Task(
        feature_name="ts-parser",
        description="Add TypeScript support",
        repo="tersecontext",
        branch_from="main",
        submitter_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    assert task.id is not None
    assert task.submitter_id == user.id
    assert task.state == "submitted"
    assert task.branch_from == "main"
    assert task.created_at is not None


@pytest.mark.asyncio
async def test_create_task_log_with_task_fk(db_session):
    """Creating a TaskLog with task_id FK links correctly and stores event and actor."""
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", role="admin")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    task = Task(
        feature_name="log-test",
        description="Test logging",
        repo="myrepo",
        submitter_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    log = TaskLog(task_id=task.id, event="created", actor_id=user.id)
    db_session.add(log)
    await db_session.commit()
    await db_session.refresh(log)

    assert log.id is not None
    assert log.task_id == task.id
    assert log.event == "created"
    assert log.actor_id == user.id
    assert log.created_at is not None


@pytest.mark.asyncio
async def test_task_submitter_relationship_loads(db_session):
    """Task.submitter relationship loads the correct User object."""
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", role="member")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    username = user.username

    task = Task(
        feature_name="rel-feature",
        description="Relationship test",
        repo="myrepo",
        submitter_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()

    result = await db_session.execute(
        select(Task).options(selectinload(Task.submitter)).where(Task.id == task.id)
    )
    loaded = result.scalar_one()

    assert loaded.submitter is not None
    assert loaded.submitter.username == username


@pytest.mark.asyncio
async def test_task_logs_relationship_loads(db_session):
    """Task.logs relationship loads all associated TaskLog entries."""
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", role="member")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    task = Task(
        feature_name="logrel-feature",
        description="Log relationship test",
        repo="myrepo",
        submitter_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    db_session.add_all([
        TaskLog(task_id=task.id, event="created"),
        TaskLog(task_id=task.id, event="researching"),
    ])
    await db_session.commit()

    result = await db_session.execute(
        select(Task).options(selectinload(Task.logs)).where(Task.id == task.id)
    )
    loaded = result.scalar_one()

    assert len(loaded.logs) == 2
    assert {log.event for log in loaded.logs} == {"created", "researching"}
