import json
import pytest
from unittest.mock import AsyncMock, patch
import redis.asyncio as aioredis


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


@pytest.mark.asyncio
async def test_read_fracture_results_creates_consumer_group():
    """xgroup_create is called with mkstream=True on the fracture stream"""
    mock_redis = AsyncMock()
    mock_redis.xreadgroup.return_value = []

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        async for _ in q.read_fracture_results():
            pass

    mock_redis.xgroup_create.assert_called_once_with(
        "stream:fracture-results", "breakdown", id="0", mkstream=True
    )


@pytest.mark.asyncio
async def test_read_fracture_results_ignores_busygroup():
    """BUSYGROUP error from xgroup_create is silently ignored"""
    mock_redis = AsyncMock()
    mock_redis.xgroup_create.side_effect = aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")
    mock_redis.xreadgroup.return_value = []

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        # Should not raise
        async for _ in q.read_fracture_results():
            pass


@pytest.mark.asyncio
async def test_read_fracture_results_decodes_bytes_to_strings():
    """Bytes keys and values in stream messages are decoded to str"""
    msg_id = b"1234567890-0"
    raw_fields = {b"task_id": b"abc-123", b"status": b"ok"}
    mock_redis = AsyncMock()
    mock_redis.xreadgroup.return_value = [
        (b"stream:fracture-results", [(msg_id, raw_fields)])
    ]

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        messages = [(mid, fields) async for mid, fields in q.read_fracture_results()]

    assert len(messages) == 1
    returned_id, returned_fields = messages[0]
    assert returned_id == msg_id
    assert returned_fields == {"task_id": "abc-123", "status": "ok"}


@pytest.mark.asyncio
async def test_read_fracture_results_empty_response_yields_nothing():
    """Empty xreadgroup response (timeout) yields no messages"""
    mock_redis = AsyncMock()
    mock_redis.xreadgroup.return_value = []

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        messages = [m async for m in q.read_fracture_results()]

    assert messages == []


@pytest.mark.asyncio
async def test_ack_fracture_result_calls_xack():
    """ack_fracture_result() calls xack on the fracture stream with the breakdown group"""
    mock_redis = AsyncMock()

    with patch("app.clients.redis.aioredis.from_url", return_value=mock_redis):
        from app.clients.redis import RedisQueue
        q = RedisQueue("redis://localhost:6379")
        await q.ack_fracture_result(b"1234567890-0")

    mock_redis.xack.assert_called_once_with(
        "stream:fracture-results", "breakdown", b"1234567890-0"
    )
