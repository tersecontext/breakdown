from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- User schemas ---

class UserCreate(BaseModel):
    username: str
    role: str = "member"


class UserUpdate(BaseModel):
    role: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Research schemas ---

class AffectedFile(BaseModel):
    file: str
    change_type: str  # "create" | "modify" | "delete"
    description: str


class Complexity(BaseModel):
    score: int
    label: str  # "low" | "medium" | "high"
    estimated_effort: str
    reasoning: str


class ResearchMetrics(BaseModel):
    files_affected: int
    files_created: int
    files_modified: int
    services_affected: int
    contract_changes: bool
    new_dependencies: list[str]
    risk_areas: list[str]


class ResearchOutput(BaseModel):
    summary: str
    affected_code: list[AffectedFile]
    complexity: Complexity
    metrics: ResearchMetrics


class TaskLogOut(BaseModel):
    id: int
    event: str
    actor_id: uuid.UUID | None
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskListItem(BaseModel):
    id: uuid.UUID
    feature_name: str
    repo: str
    state: str
    submitter_id: uuid.UUID
    submitter_username: str
    created_at: datetime

    model_config = {"from_attributes": False}


# --- Task schemas ---

class TaskCreate(BaseModel):
    feature_name: str
    description: str
    repo: str
    branch_from: str = "main"
    additional_context: list[str] = []
    optional_answers: dict[str, Any] = {}


class TaskReject(BaseModel):
    reason: str | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    feature_name: str
    description: str
    repo: str
    branch_from: str
    state: str
    submitter_id: uuid.UUID
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None
    source_channel: str | None
    slack_channel_id: str | None
    slack_thread_ts: str | None
    additional_context: list[Any]
    optional_answers: dict[str, Any]
    tc_context: str | None
    research: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    logs: list[TaskLogOut] = []

    model_config = {"from_attributes": True}


# --- Repo schemas ---

class RepoOut(BaseModel):
    name: str
    indexed: bool


class BranchOut(BaseModel):
    name: str


# --- Auth schemas ---

class LoginRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=1)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class SetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=1)
