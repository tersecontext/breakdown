import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SOURCE_DIRS", "/tmp")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

# Patch AsyncMock so that when no explicit side_effect/return_value is set,
# the return value of awaitable methods is a MagicMock (not AsyncMock).
# This ensures `result.scalar_one_or_none()` returns None by default,
# matching SQLAlchemy session semantics in tests.
_original_get_child_mock = AsyncMock._get_child_mock


def _patched_get_child_mock(self, **kw):
    if kw.get("_new_name") == "()":
        rv = MagicMock(**kw)
        rv.scalar_one_or_none.return_value = None
        rv.scalars.return_value.all.return_value = []
        return rv
    return _original_get_child_mock(self, **kw)


AsyncMock._get_child_mock = _patched_get_child_mock
