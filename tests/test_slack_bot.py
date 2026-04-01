# tests/test_slack_bot.py
import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def make_app_state():
    state = MagicMock()
    state.tc_client = AsyncMock()
    state.llm_client = AsyncMock()
    state.redis = AsyncMock()
    state.background_tasks = set()
    return state


def make_mock_session(user=None, task=None):
    """Session that returns user on first execute, task on second."""
    session = AsyncMock()
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    results = []
    if user is not None:
        r = MagicMock()
        r.scalar_one_or_none.return_value = user
        results.append(r)
    if task is not None:
        r = MagicMock()
        r.scalar_one_or_none.return_value = task
        results.append(r)

    if results:
        session.execute.side_effect = results
    return session


@pytest.mark.asyncio
async def test_message_handler_ignores_bot_messages():
    """handle_message does nothing when the message has bot_id"""
    from app.clients.slack_bot import SlackBot
    bot = SlackBot(make_app_state(), channel_id="C123")

    say = AsyncMock()
    message = {"channel": "C123", "text": "hello", "bot_id": "B1"}
    await bot._handle_message(message, say)
    say.assert_not_called()


@pytest.mark.asyncio
async def test_message_handler_ignores_wrong_channel():
    """handle_message does nothing when channel does not match"""
    from app.clients.slack_bot import SlackBot
    bot = SlackBot(make_app_state(), channel_id="C123")

    say = AsyncMock()
    message = {"channel": "C999", "text": "hello", "ts": "1.0"}
    await bot._handle_message(message, say)
    say.assert_not_called()


@pytest.mark.asyncio
async def test_message_handler_posts_repo_buttons():
    """handle_message posts a 'Which repo?' message with one button per repo"""
    from app.clients.slack_bot import SlackBot
    bot = SlackBot(make_app_state(), channel_id="C123")

    say = AsyncMock()
    message = {"channel": "C123", "text": "add typescript support", "ts": "1.0"}

    repos = [{"name": "tersecontext", "path": "/foo"}, {"name": "breakdown", "path": "/bar"}]
    with patch("app.clients.slack_bot._find_repos", return_value=repos):
        await bot._handle_message(message, say)

    say.assert_called_once()
    call_kwargs = say.call_args.kwargs
    assert call_kwargs.get("thread_ts") == "1.0"
    blocks = call_kwargs["blocks"]
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1
    assert len(action_blocks[0]["elements"]) == 2
    action_ids = {e["action_id"] for e in action_blocks[0]["elements"]}
    assert action_ids == {"select_repo"}


@pytest.mark.asyncio
async def test_repo_select_creates_user_if_not_exists():
    """select_repo action auto-creates user with role='member' when not found"""
    from app.clients.slack_bot import SlackBot

    mock_session = make_mock_session(user=None)  # user not found
    mock_client = AsyncMock()
    mock_client.users_info.return_value = {
        "user": {"profile": {"display_name": "alice"}}
    }

    bot = SlackBot(make_app_state(), channel_id="C123")

    body = {
        "user": {"id": "U1"},
        "channel": {"id": "C123"},
        "actions": [{"action_id": "select_repo", "value": '{"repo": "myrepo", "ts": "1.0"}'}],
        "message": {"ts": "1.1"},
    }
    ack = AsyncMock()

    with patch("app.clients.slack_bot.AsyncSessionLocal", return_value=mock_session), \
         patch("app.clients.slack_bot.asyncio.create_task"):
        await bot._handle_repo_select(ack, body, mock_client)

    ack.assert_awaited_once()
    # User.add called with a User object (role=member)
    added_calls = mock_session.add.call_args_list
    assert any("User" in type(c.args[0]).__name__ for c in added_calls)


@pytest.mark.asyncio
async def test_repo_select_creates_task_and_posts_researching():
    """select_repo action creates a Task and posts 'Researching...' in thread"""
    from app.clients.slack_bot import SlackBot
    from app.models import User

    existing_user = MagicMock(spec=User)
    existing_user.id = uuid.uuid4()
    existing_user.role = "member"
    existing_user.username = "alice"

    # pending message stored in bot
    bot = SlackBot(make_app_state(), channel_id="C123")
    bot._pending_messages["C123:1.0"] = "add typescript support"

    mock_session = make_mock_session(user=existing_user)
    mock_client = AsyncMock()
    mock_client.users_info.return_value = {
        "user": {"profile": {"display_name": "alice"}}
    }

    body = {
        "user": {"id": "U1"},
        "channel": {"id": "C123"},
        "actions": [{"action_id": "select_repo", "value": '{"repo": "myrepo", "ts": "1.0"}'}],
        "message": {"ts": "1.1"},
    }
    ack = AsyncMock()

    mock_task_ref = MagicMock()
    with patch("app.clients.slack_bot.AsyncSessionLocal", return_value=mock_session), \
         patch("app.clients.slack_bot.asyncio.create_task", return_value=mock_task_ref) as mock_ct:
        await bot._handle_repo_select(ack, body, mock_client)

    # research was spawned
    mock_ct.assert_called_once()
    # "Researching..." was posted in thread
    mock_client.chat_postMessage.assert_called_once()
    kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "C123"
    assert kwargs["thread_ts"] == "1.0"
    assert "esearch" in kwargs.get("text", "")


@pytest.mark.asyncio
async def test_approve_action_approves_if_admin():
    """approve_task action approves task when clicking user is admin"""
    from app.clients.slack_bot import SlackBot
    from app.models import User, Task

    admin_user = MagicMock(spec=User)
    admin_user.id = uuid.uuid4()
    admin_user.role = "admin"
    admin_user.username = "boss"

    task = MagicMock(spec=Task)
    task.id = uuid.uuid4()
    task.state = "researched"
    task.slack_channel_id = "C123"
    task.slack_thread_ts = "1.0"
    task.submitter = admin_user

    mock_session = make_mock_session(user=admin_user, task=task)
    mock_client = AsyncMock()
    mock_client.users_info.return_value = {
        "user": {"profile": {"display_name": "boss"}}
    }

    app_state = make_app_state()
    bot = SlackBot(app_state, channel_id="C123")

    task_id = str(task.id)
    body = {
        "user": {"id": "U1"},
        "channel": {"id": "C123"},
        "actions": [{"action_id": "approve_task", "value": task_id}],
    }
    ack = AsyncMock()

    with patch("app.clients.slack_bot.AsyncSessionLocal", return_value=mock_session), \
         patch("app.clients.slack_bot.publish_approved_task", new_callable=AsyncMock):
        await bot._handle_approve(ack, body, mock_client)

    ack.assert_awaited_once()
    assert task.state == "approved"
    mock_client.chat_postMessage.assert_called_once()
    kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert "boss" in kwargs.get("text", "")


@pytest.mark.asyncio
async def test_approve_action_ephemeral_if_not_admin():
    """approve_task action sends ephemeral message when user is not admin"""
    from app.clients.slack_bot import SlackBot
    from app.models import User

    member_user = MagicMock(spec=User)
    member_user.id = uuid.uuid4()
    member_user.role = "member"
    member_user.username = "joe"

    mock_session = make_mock_session(user=member_user)
    mock_client = AsyncMock()
    mock_client.users_info.return_value = {
        "user": {"profile": {"display_name": "joe"}}
    }

    bot = SlackBot(make_app_state(), channel_id="C123")

    body = {
        "user": {"id": "U1"},
        "channel": {"id": "C123"},
        "actions": [{"action_id": "approve_task", "value": str(uuid.uuid4())}],
    }
    ack = AsyncMock()

    with patch("app.clients.slack_bot.AsyncSessionLocal", return_value=mock_session):
        await bot._handle_approve(ack, body, mock_client)

    ack.assert_awaited_once()
    mock_client.chat_postEphemeral.assert_called_once()
    kwargs = mock_client.chat_postEphemeral.call_args.kwargs
    assert "admin" in kwargs.get("text", "").lower()


@pytest.mark.asyncio
async def test_reject_action_rejects_if_admin():
    """reject_task action rejects task when clicking user is admin"""
    from app.clients.slack_bot import SlackBot
    from app.models import User, Task

    admin_user = MagicMock(spec=User)
    admin_user.id = uuid.uuid4()
    admin_user.role = "admin"
    admin_user.username = "boss"

    task = MagicMock(spec=Task)
    task.id = uuid.uuid4()
    task.state = "researched"
    task.slack_channel_id = "C123"
    task.slack_thread_ts = "1.0"

    mock_session = make_mock_session(user=admin_user, task=task)
    mock_client = AsyncMock()
    mock_client.users_info.return_value = {
        "user": {"profile": {"display_name": "boss"}}
    }

    bot = SlackBot(make_app_state(), channel_id="C123")

    body = {
        "user": {"id": "U1"},
        "channel": {"id": "C123"},
        "actions": [{"action_id": "reject_task", "value": str(task.id)}],
    }
    ack = AsyncMock()

    with patch("app.clients.slack_bot.AsyncSessionLocal", return_value=mock_session):
        await bot._handle_reject(ack, body, mock_client)

    ack.assert_awaited_once()
    assert task.state == "rejected"
    mock_client.chat_postMessage.assert_called_once()
    kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert "boss" in kwargs.get("text", "")
