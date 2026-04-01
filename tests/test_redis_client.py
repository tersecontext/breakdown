import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_push_approved_xadds_to_stream():
    """push_approved() calls XADD on stream:breakdown-approved with bundle fields"""
    mock_redis = AsyncMock()

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        await q.push_approved({
            "task_id": "abc-123",
            "feature_name": "my-feature",
            "research": {"summary": "test"},
            "additional_context": ["file.py"],
            "optional_answers": {"scope_notes": "narrow"},
        })

    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "stream:breakdown-approved"
    fields = call_args[0][1]
    assert fields["task_id"] == "abc-123"
    assert fields["feature_name"] == "my-feature"
    # Complex fields are JSON-serialized
    assert fields["research"] == json.dumps({"summary": "test"})
    assert fields["additional_context"] == json.dumps(["file.py"])
    assert fields["optional_answers"] == json.dumps({"scope_notes": "narrow"})


@pytest.mark.asyncio
async def test_close_calls_aclose():
    """close() calls aclose() on the underlying Redis connection"""
    mock_redis = AsyncMock()

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        await q.close()

    mock_redis.aclose.assert_called_once()
