# tests/test_notifier.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_task(state="researched", source_channel="slack", role="member"):
    task = MagicMock()
    task.id = uuid.uuid4()
    task.feature_name = "add typescript support"
    task.slack_channel_id = "C123"
    task.slack_thread_ts = "111.222"
    task.source_channel = source_channel
    task.error_message = "oops"
    task.state = state
    task.submitter = MagicMock()
    task.submitter.role = role
    task.research = {
        "summary": "Adds TS parsing.",
        "affected_code": [{"file": "parser.py", "change_type": "modify", "description": "add ts"}],
        "complexity": {"score": 3, "label": "low", "estimated_effort": "2-4 hours", "reasoning": "small"},
        "metrics": {
            "files_affected": 1, "files_created": 0, "files_modified": 1,
            "services_affected": 1, "contract_changes": False,
            "new_dependencies": [], "risk_areas": ["none"],
        },
    }
    return task


@pytest.mark.asyncio
async def test_post_research_result_skips_non_slack():
    """Does nothing when source_channel is not 'slack'"""
    from app.engine.notifier import post_research_result
    task = make_task(source_channel="api")
    client = AsyncMock()
    await post_research_result(task, client, is_admin=False)
    client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
async def test_post_research_result_posts_to_thread():
    """Posts to the correct channel and thread_ts"""
    from app.engine.notifier import post_research_result
    task = make_task()
    client = AsyncMock()
    await post_research_result(task, client, is_admin=False)
    client.chat_postMessage.assert_called_once()
    kwargs = client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "C123"
    assert kwargs["thread_ts"] == "111.222"
    assert "blocks" in kwargs


@pytest.mark.asyncio
async def test_post_research_result_includes_approve_buttons_for_admin():
    """Admin submitter gets Approve/Reject action buttons"""
    from app.engine.notifier import post_research_result
    task = make_task(role="admin")
    client = AsyncMock()
    await post_research_result(task, client, is_admin=True)
    kwargs = client.chat_postMessage.call_args.kwargs
    blocks = kwargs["blocks"]
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1
    action_ids = [e["action_id"] for e in action_blocks[0]["elements"]]
    assert "approve_task" in action_ids
    assert "reject_task" in action_ids


@pytest.mark.asyncio
async def test_post_research_result_shows_waiting_for_member():
    """Member submitter gets 'Waiting for admin approval' text, no action buttons"""
    from app.engine.notifier import post_research_result
    task = make_task(role="member")
    client = AsyncMock()
    await post_research_result(task, client, is_admin=False)
    kwargs = client.chat_postMessage.call_args.kwargs
    blocks = kwargs["blocks"]
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 0
    all_text = str(blocks)
    assert "admin" in all_text.lower()


@pytest.mark.asyncio
async def test_post_error_skips_non_slack():
    """Does nothing when source_channel is not 'slack'"""
    from app.engine.notifier import post_error
    task = make_task(state="failed", source_channel="api")
    client = AsyncMock()
    await post_error(task, client)
    client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
async def test_post_error_posts_error_to_thread():
    """Posts error message to the correct thread"""
    from app.engine.notifier import post_error
    task = make_task(state="failed")
    client = AsyncMock()
    await post_error(task, client)
    client.chat_postMessage.assert_called_once()
    kwargs = client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "C123"
    assert kwargs["thread_ts"] == "111.222"
    assert "oops" in str(kwargs.get("text", "")) or "oops" in str(kwargs.get("blocks", ""))


@pytest.mark.asyncio
async def test_post_research_result_handles_slack_exception():
    """Does not raise when Slack API call throws"""
    from app.engine.notifier import post_research_result
    task = make_task()
    client = AsyncMock()
    client.chat_postMessage.side_effect = Exception("Slack API down")
    # Should not raise
    await post_research_result(task, client, is_admin=False)


@pytest.mark.asyncio
async def test_post_research_result_handles_none_research():
    """Does not raise when task.research is None"""
    from app.engine.notifier import post_research_result
    task = make_task()
    task.research = None
    client = AsyncMock()
    await post_research_result(task, client, is_admin=False)
    client.chat_postMessage.assert_called_once()
