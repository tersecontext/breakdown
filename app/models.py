from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    role: Mapped[str] = mapped_column(nullable=False, default="member", server_default="member")
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    submitted_tasks: Mapped[list[Task]] = relationship(
        "Task", foreign_keys="Task.submitter_id", back_populates="submitter"
    )
    approved_tasks: Mapped[list[Task]] = relationship(
        "Task", foreign_keys="Task.approved_by_id", back_populates="approved_by"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    feature_name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    repo: Mapped[str] = mapped_column(nullable=False)
    branch_from: Mapped[str] = mapped_column(nullable=False, default="main", server_default="main")
    state: Mapped[str] = mapped_column(nullable=False, default="submitted", server_default="submitted")
    submitter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    source_channel: Mapped[str | None] = mapped_column(nullable=True)
    slack_channel_id: Mapped[str | None] = mapped_column(nullable=True)
    slack_thread_ts: Mapped[str | None] = mapped_column(nullable=True)
    additional_context: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    optional_answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    tc_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    research: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    submitter: Mapped[User] = relationship("User", foreign_keys=[submitter_id], back_populates="submitted_tasks")
    approved_by: Mapped[User | None] = relationship("User", foreign_keys=[approved_by_id], back_populates="approved_tasks")
    logs: Mapped[list[TaskLog]] = relationship("TaskLog", back_populates="task")


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    event: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship("Task", back_populates="logs")
    actor: Mapped[User | None] = relationship("User", foreign_keys=[actor_id])
