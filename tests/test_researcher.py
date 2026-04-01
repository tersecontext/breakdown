import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


VALID_RESEARCH = {
    "summary": "This adds TypeScript parsing.",
    "affected_code": [{"file": "parser.py", "change_type": "modify", "description": "add ts handling"}],
    "complexity": {"score": 3, "label": "low", "estimated_effort": "2-4 hours", "reasoning": "small change"},
    "metrics": {
        "files_affected": 1, "files_created": 0, "files_modified": 1,
        "services_affected": 1, "contract_changes": False,
        "new_dependencies": [], "risk_areas": []
    }
}


def make_mock_task(task_id=None):
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.feature_name = "ts-parser"
    task.description = "Add TypeScript support"
    task.repo = "tersecontext"
    task.optional_answers = {}
    task.additional_context = []
    task.tc_context = None
    task.research = None
    task.state = "submitted"
    task.logs = []
    return task


def make_mock_session(task):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    session.execute.return_value = result
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_research_happy_path_sets_researched_state():
    """research() sets state='researched' and stores research dict on success"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "some code context"

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(VALID_RESEARCH)
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = mock_llm_response

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "researched"
    assert task.research == VALID_RESEARCH
    assert task.tc_context == "some code context"


@pytest.mark.asyncio
async def test_research_passes_repo_to_tc_client():
    """research() passes task.repo to tc_client.query()"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(VALID_RESEARCH)
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = mock_llm_response

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    mock_tc.query.assert_called_once()
    _, kwargs = mock_tc.query.call_args
    assert kwargs.get("repo") == "tersecontext"


@pytest.mark.asyncio
async def test_research_retries_on_json_parse_failure():
    """research() retries LLM call once if the first response is not valid JSON"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    bad_response = MagicMock()
    bad_response.content = "not valid json at all"
    good_response = MagicMock()
    good_response.content = json.dumps(VALID_RESEARCH)

    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = [bad_response, good_response]

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert mock_llm.chat.call_count == 2
    assert task.state == "researched"


@pytest.mark.asyncio
async def test_research_sets_failed_on_tc_error():
    """research() sets state='failed' when TerseContext raises"""
    from app.clients.tersecontext import TerseContextError
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.side_effect = TerseContextError("TC down")

    mock_llm = AsyncMock()

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "failed"
    assert "TC down" in task.error_message


@pytest.mark.asyncio
async def test_research_sets_failed_when_both_json_attempts_fail():
    """research() sets state='failed' when both LLM calls return non-JSON"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    bad_response = MagicMock()
    bad_response.content = "not json"
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = bad_response

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "failed"
    assert task.error_message is not None


@pytest.mark.asyncio
async def test_research_sets_failed_on_pydantic_validation_error():
    """research() sets state='failed' when LLM returns JSON but with wrong structure"""
    task = make_mock_task()
    mock_session = make_mock_session(task)

    mock_tc = AsyncMock()
    mock_tc.query.return_value = "context"

    # Valid JSON but missing required fields
    bad_research = MagicMock()
    bad_research.content = json.dumps({"summary": "ok"})  # missing affected_code etc.
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = bad_research

    with patch("app.engine.researcher.AsyncSessionLocal", return_value=mock_session):
        from app.engine.researcher import research
        await research(task.id, mock_tc, mock_llm)

    assert task.state == "failed"
    assert task.research is None
