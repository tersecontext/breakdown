import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone


TC_CONTEXT_SAMPLE = """## Layer 3 — Registry
fn:1  authenticate(user: str, pwd: str) -> bool       [auth/service.py:34]
spec.75%
fn:2  _hash_password(pw: str, salt: bytes) -> str     [auth/crypto.py:12]
static
cls:1  UserManager                                     [auth/manager.py:5]
fn:3  validate_token(tok: str) -> dict                [auth/service.py:80]

## Layer 4 — Edges
fn:1 -> fn:2  calls
"""


def make_task():
    task = MagicMock()
    task.id = uuid.uuid4()
    task.feature_name = "ts-parser"
    task.description = "Add TypeScript support"
    task.repo = "tersecontext"
    task.branch_from = "main"
    task.tc_context = TC_CONTEXT_SAMPLE
    task.research = {"summary": "test research"}
    task.additional_context = ["file.py"]
    task.optional_answers = {"scope_notes": "narrow"}
    task.approved_at = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
    task.submitter = MagicMock()
    task.submitter.username = "kmcbeth"
    return task


def make_admin():
    admin = MagicMock()
    admin.username = "admin"
    return admin


def test_parse_tc_file_paths_extracts_unique_paths():
    from app.engine.queue import parse_tc_file_paths

    paths = parse_tc_file_paths(TC_CONTEXT_SAMPLE)
    assert paths == ["auth/service.py", "auth/crypto.py", "auth/manager.py"]


def test_parse_tc_file_paths_empty_string():
    from app.engine.queue import parse_tc_file_paths

    assert parse_tc_file_paths("") == []


def test_parse_tc_file_paths_no_registry():
    from app.engine.queue import parse_tc_file_paths

    assert parse_tc_file_paths("## Layer 4 — Edges\nfn:1 -> fn:2  calls\n") == []


@pytest.mark.asyncio
async def test_publish_approved_task_calls_push_approved():
    """publish_approved_task() calls redis.push_approved with the correct bundle"""
    from app.engine.queue import publish_approved_task

    task = make_task()
    admin = make_admin()
    mock_redis = AsyncMock()

    await publish_approved_task(task, admin, mock_redis)

    mock_redis.push_approved.assert_called_once()
    bundle = mock_redis.push_approved.call_args[0][0]

    assert bundle["task_id"] == str(task.id)
    assert bundle["feature_name"] == "ts-parser"
    assert bundle["description"] == "Add TypeScript support"
    assert bundle["repo"] == "tersecontext"
    assert bundle["branch_from"] == "main"
    assert bundle["submitter"] == "kmcbeth"
    assert bundle["approved_by"] == "admin"
    assert bundle["approved_at"] == "2026-03-31T12:00:00+00:00"
    assert bundle["tc_context"] == TC_CONTEXT_SAMPLE
    assert bundle["research"] == {"summary": "test research"}
    assert bundle["additional_context"] == ["file.py"]
    assert bundle["optional_answers"] == {"scope_notes": "narrow"}
    assert bundle["file_paths"] == [
        "auth/service.py",
        "auth/crypto.py",
        "auth/manager.py",
    ]


@pytest.mark.asyncio
async def test_publish_approved_task_uses_empty_string_when_tc_context_is_none():
    """publish_approved_task() sends empty string for tc_context when it is None"""
    from app.engine.queue import publish_approved_task

    task = make_task()
    task.tc_context = None
    admin = make_admin()
    mock_redis = AsyncMock()

    await publish_approved_task(task, admin, mock_redis)

    bundle = mock_redis.push_approved.call_args[0][0]
    assert bundle["tc_context"] == ""
    assert bundle["file_paths"] == []
