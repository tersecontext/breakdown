import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_admin
from app.db import get_session
from app.engine.queue import publish_approved_task
from app.engine.researcher import research
from app.models import Task, TaskLog, User
from app.schemas import TaskCreate, TaskListItem, TaskOut, TaskReject

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/tasks", status_code=201, response_model=TaskOut)
async def create_task(
    body: TaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    task = Task(
        feature_name=body.feature_name,
        description=body.description,
        repo=body.repo,
        branch_from=body.branch_from,
        additional_context=body.additional_context,
        optional_answers=body.optional_answers,
        submitter_id=user.id,
        state="submitted",
    )
    session.add(task)
    session.add(TaskLog(task_id=task.id, event="task_created", actor_id=user.id))
    await session.commit()

    result = await session.execute(
        select(Task).where(Task.id == task.id).options(selectinload(Task.logs))
    )
    task = result.scalar_one()

    t = asyncio.create_task(
        research(task.id, request.app.state.tc_client, request.app.state.llm_client)
    )
    request.app.state.background_tasks.add(t)
    t.add_done_callback(request.app.state.background_tasks.discard)

    return task


@router.get("/api/tasks", response_model=list[TaskListItem])
async def list_tasks(
    state: str | None = None,
    repo: str | None = None,
    submitter: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Task, User.username).join(User, Task.submitter_id == User.id)
    if state:
        stmt = stmt.where(Task.state == state)
    if repo:
        stmt = stmt.where(Task.repo == repo)
    if submitter:
        stmt = stmt.where(User.username == submitter)

    rows = (await session.execute(stmt)).all()
    return [
        TaskListItem(
            id=task.id,
            feature_name=task.feature_name,
            repo=task.repo,
            state=task.state,
            submitter_id=task.submitter_id,
            submitter_username=username,
            created_at=task.created_at,
        )
        for task, username in rows
    ]


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Task).where(Task.id == task_id).options(selectinload(Task.logs))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/api/tasks/{task_id}/approve", response_model=TaskOut)
async def approve_task(
    task_id: UUID,
    request: Request,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.submitter), selectinload(Task.logs))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "researched":
        raise HTTPException(status_code=409, detail=f"Task is in state '{task.state}', expected 'researched'")

    task.state = "approved"
    task.approved_by_id = user.id
    task.approved_at = datetime.now(timezone.utc)
    session.add(TaskLog(task_id=task.id, event="task_approved", actor_id=user.id))
    await session.commit()

    try:
        await publish_approved_task(task, user, request.app.state.redis)
    except Exception as e:
        logger.error("Redis publish failed for task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Redis publish failed")

    session.add(TaskLog(task_id=task.id, event="task_queued", actor_id=user.id))
    await session.commit()

    result = await session.execute(
        select(Task).where(Task.id == task_id).options(selectinload(Task.logs))
    )
    return result.scalar_one()


@router.post("/api/tasks/{task_id}/reject", response_model=TaskOut)
async def reject_task(
    task_id: UUID,
    body: TaskReject = TaskReject(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Task).where(Task.id == task_id).options(selectinload(Task.logs))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "researched":
        raise HTTPException(status_code=409, detail=f"Task is in state '{task.state}', expected 'researched'")

    task.state = "rejected"
    detail = {"reason": body.reason} if body.reason else None
    session.add(TaskLog(task_id=task.id, event="task_rejected", actor_id=user.id, detail=detail))
    await session.commit()
    return task
