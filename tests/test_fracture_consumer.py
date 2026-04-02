import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app_state(slack_client=None):
    state = MagicMock()
    state.redis = AsyncMock()
    state.slack_web_client = slack_client
    return state


def make_task(task_id, source_channel="slack"):
    task = MagicMock()
    task.id = task_id
    task.state = "approved"
    task.error_message = None
    task.source_channel = source_channel
    task.slack_channel_id = "C123"
    task.slack_thread_ts = "111.222"
    task.feature_name = "test feature"
    return task


def make_session_mock(task):
    """Return a mock AsyncSessionLocal that yields a session whose execute()
    returns the given task (or None if task is None)."""
    session = AsyncMock()
    session.execute.return_value.scalar_one_or_none.return_value = task
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session)
    return session_factory, session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_ok_message_sets_state_decomposed():
    """status=ok sets task.state='decomposed', writes TaskLog, acks, no post_error"""
    task_id = uuid.uuid4()
    task = make_task(task_id)
    app_state = make_app_state(slack_client=AsyncMock())
    session_factory, session = make_session_mock(task)
    msg_id = b"1-0"
    fields = {"task_id": str(task_id), "status": "ok"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    assert task.state == "decomposed"
    assert task.error_message is None
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.event == "decomposed"
    session.commit.assert_called_once()
    mock_post_error.assert_not_called()
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_error_message_sets_state_failed():
    """status=error sets task.state='failed', sets error_message, writes TaskLog,
    calls post_error, acks"""
    task_id = uuid.uuid4()
    task = make_task(task_id)
    slack_client = AsyncMock()
    app_state = make_app_state(slack_client=slack_client)
    session_factory, session = make_session_mock(task)
    msg_id = b"2-0"
    fields = {"task_id": str(task_id), "status": "error", "error": "pipeline crashed"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    assert task.state == "failed"
    assert task.error_message == "pipeline crashed"
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.event == "fracture_failed"
    assert added.detail == {"error": "pipeline crashed"}
    session.commit.assert_called_once()
    mock_post_error.assert_called_once_with(task, slack_client)
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_task_not_found_acks_without_db_writes():
    """If task_id is not in the DB, logs a warning and acks — no state changes"""
    task_id = uuid.uuid4()
    app_state = make_app_state()
    session_factory, session = make_session_mock(task=None)
    msg_id = b"3-0"
    fields = {"task_id": str(task_id), "status": "ok"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error, \
         patch("app.engine.fracture_consumer.logger") as mock_logger:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    session.add.assert_not_called()
    session.commit.assert_not_called()
    mock_post_error.assert_not_called()
    mock_logger.warning.assert_called()
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_db_commit_failure_still_acks():
    """If session.commit() raises, the message is still acked"""
    task_id = uuid.uuid4()
    task = make_task(task_id)
    app_state = make_app_state()
    session_factory, session = make_session_mock(task)
    session.commit.side_effect = Exception("DB connection lost")
    msg_id = b"4-0"
    fields = {"task_id": str(task_id), "status": "ok"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error"):
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)


async def test_slack_client_none_does_not_call_post_error():
    """When slack_web_client is None and status=error, post_error is not called"""
    task_id = uuid.uuid4()
    task = make_task(task_id, source_channel="slack")
    app_state = make_app_state(slack_client=None)
    session_factory, session = make_session_mock(task)
    msg_id = b"5-0"
    fields = {"task_id": str(task_id), "status": "error", "error": "boom"}

    with patch("app.engine.fracture_consumer.AsyncSessionLocal", session_factory), \
         patch("app.engine.fracture_consumer.post_error") as mock_post_error:
        from app.engine.fracture_consumer import _handle_message
        await _handle_message(msg_id, fields, app_state)

    # No crash, acked, post_error not called
    mock_post_error.assert_not_called()
    app_state.redis.ack_fracture_result.assert_called_once_with(msg_id)
    assert task.state == "failed"
