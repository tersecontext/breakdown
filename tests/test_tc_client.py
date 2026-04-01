import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.clients.tersecontext import TerseContextClient, TerseContextError


@pytest.mark.asyncio
async def test_query_posts_and_returns_context():
    """query() POSTs to /query and returns response text as the context string"""
    mock_response = MagicMock()
    mock_response.text = "this is the context"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    tc = TerseContextClient("http://localhost:8090", client=mock_client)
    result = await tc.query("how does the parser work")

    mock_client.post.assert_called_once_with(
        "http://localhost:8090/query",
        json={"query": "how does the parser work", "repo": None},
    )
    assert result == "this is the context"


@pytest.mark.asyncio
async def test_query_sends_repo_when_specified():
    """query() includes repo in request body when provided"""
    mock_response = MagicMock()
    mock_response.text = "context"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    tc = TerseContextClient("http://localhost:8090", client=mock_client)
    await tc.query("test query", repo="myrepo")

    mock_client.post.assert_called_once_with(
        "http://localhost:8090/query",
        json={"query": "test query", "repo": "myrepo"},
    )


@pytest.mark.asyncio
async def test_query_retries_twice_before_succeeding():
    """query() retries up to 2 times (3 total attempts) and succeeds on the 3rd"""
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ConnectError("connection refused")
        response = MagicMock()
        response.text = "success context"
        response.raise_for_status = MagicMock()
        return response

    mock_client = AsyncMock()
    mock_client.post = mock_post

    with patch("asyncio.sleep"):
        tc = TerseContextClient("http://localhost:8090", client=mock_client)
        result = await tc.query("test")

    assert call_count == 3
    assert result == "success context"


@pytest.mark.asyncio
async def test_query_raises_terse_context_error_when_all_retries_fail():
    """query() raises TerseContextError after all 3 attempts fail"""
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.ConnectError("connection refused")

    with patch("asyncio.sleep"):
        tc = TerseContextClient("http://localhost:8090", client=mock_client)
        with pytest.raises(TerseContextError):
            await tc.query("test")

    assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_health_returns_json_when_reachable():
    """health() GETs /health and returns the JSON dict"""
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "ok", "repos": 5}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    tc = TerseContextClient("http://localhost:8090", client=mock_client)
    result = await tc.health()

    mock_client.get.assert_called_once_with("http://localhost:8090/health")
    assert result == {"status": "ok", "repos": 5}


@pytest.mark.asyncio
async def test_health_returns_none_when_unreachable():
    """health() returns None when the service cannot be reached"""
    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError("unreachable")

    tc = TerseContextClient("http://localhost:8090", client=mock_client)
    result = await tc.health()

    assert result is None


@pytest.mark.asyncio
async def test_close_closes_httpx_client():
    """close() calls aclose() on the underlying httpx AsyncClient"""
    mock_client = AsyncMock()
    tc = TerseContextClient("http://localhost:8090", client=mock_client)
    await tc.close()
    mock_client.aclose.assert_called_once()
