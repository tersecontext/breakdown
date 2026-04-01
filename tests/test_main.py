import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_migrations


@pytest.mark.asyncio
async def test_run_migrations_success():
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await run_migrations()

    mock_exec.assert_called_once_with("alembic", "upgrade", "head")


@pytest.mark.asyncio
async def test_run_migrations_failure_raises():
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=1)
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="alembic upgrade head failed"):
            await run_migrations()
