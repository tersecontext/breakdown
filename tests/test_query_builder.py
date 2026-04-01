from unittest.mock import MagicMock


def make_task(description, optional_answers=None):
    task = MagicMock()
    task.description = description
    task.optional_answers = optional_answers or {}
    return task


def test_build_query_returns_description_when_no_optional_answers():
    """build_query returns just the description when optional_answers is empty"""
    from app.engine.query_builder import build_query
    task = make_task("Add TypeScript support to the parser")
    result = build_query(task)
    assert result == "Add TypeScript support to the parser"


def test_build_query_appends_known_optional_answer_keys():
    """build_query appends scope_notes, architecture_notes, constraints, testing_notes"""
    from app.engine.query_builder import build_query
    task = make_task(
        "Add TypeScript support",
        optional_answers={
            "scope_notes": "only the parser service",
            "architecture_notes": "use visitor pattern",
            "constraints": "no new dependencies",
            "testing_notes": "unit tests only",
        },
    )
    result = build_query(task)
    assert "Scope: only the parser service" in result
    assert "Architecture: use visitor pattern" in result
    assert "Constraints: no new dependencies" in result
    assert "Testing: unit tests only" in result


def test_build_query_ignores_empty_optional_answer_values():
    """build_query skips optional_answers keys with empty string values"""
    from app.engine.query_builder import build_query
    task = make_task("Add TypeScript support", optional_answers={"scope_notes": ""})
    result = build_query(task)
    assert "Scope:" not in result


def test_build_query_ignores_unknown_optional_answer_keys():
    """build_query ignores keys not in the known set"""
    from app.engine.query_builder import build_query
    task = make_task("Add TypeScript support", optional_answers={"unknown_key": "value"})
    result = build_query(task)
    assert "unknown_key" not in result
    assert "value" not in result


def test_build_query_truncates_to_500_chars():
    """build_query hard-truncates output to 500 characters"""
    from app.engine.query_builder import build_query
    task = make_task("x" * 600)
    result = build_query(task)
    assert len(result) == 500


def test_build_query_does_not_truncate_when_under_500():
    """build_query returns full string when under 500 characters"""
    from app.engine.query_builder import build_query
    task = make_task("short description")
    result = build_query(task)
    assert result == "short description"
    assert len(result) < 500
