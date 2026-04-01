import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_get_repos_returns_repos_with_git_dir():
    """GET /api/repos returns repos that have a .git directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = os.path.join(tmpdir, "myrepo")
        os.makedirs(os.path.join(repo_dir, ".git"))

        non_repo = os.path.join(tmpdir, "notarepo")
        os.makedirs(non_repo)

        with patch("app.routes.repos.settings") as mock_settings, \
             patch("app.routes.repos.TerseContextClient") as mock_tc_class:

            mock_settings.source_dirs = tmpdir
            mock_settings.tersecontext_url = "http://localhost:8090"

            mock_tc = AsyncMock()
            mock_tc.health.return_value = None
            mock_tc_class.return_value = mock_tc

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/repos")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "myrepo"
    assert data[0]["path"] == repo_dir


@pytest.mark.asyncio
async def test_get_repos_tc_indexed_true_when_health_returns_data():
    """GET /api/repos sets tc_indexed=True when TerseContext health check responds"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = os.path.join(tmpdir, "myrepo")
        os.makedirs(os.path.join(repo_dir, ".git"))

        with patch("app.routes.repos.settings") as mock_settings, \
             patch("app.routes.repos.TerseContextClient") as mock_tc_class:

            mock_settings.source_dirs = tmpdir
            mock_settings.tersecontext_url = "http://localhost:8090"

            mock_tc = AsyncMock()
            mock_tc.health.return_value = {"status": "ok", "node_count": 42, "last_indexed": "2024-01-01"}
            mock_tc_class.return_value = mock_tc

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/repos")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["tc_indexed"] is True
    assert data[0]["tc_node_count"] == 42
    assert data[0]["tc_last_indexed"] == "2024-01-01"


@pytest.mark.asyncio
async def test_get_repos_tc_indexed_false_when_health_returns_none():
    """GET /api/repos sets tc_indexed=False when TerseContext is unreachable"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = os.path.join(tmpdir, "myrepo")
        os.makedirs(os.path.join(repo_dir, ".git"))

        with patch("app.routes.repos.settings") as mock_settings, \
             patch("app.routes.repos.TerseContextClient") as mock_tc_class:

            mock_settings.source_dirs = tmpdir
            mock_settings.tersecontext_url = "http://localhost:8090"

            mock_tc = AsyncMock()
            mock_tc.health.return_value = None
            mock_tc_class.return_value = mock_tc

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/repos")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["tc_indexed"] is False
    assert data[0]["tc_node_count"] is None
    assert data[0]["tc_last_indexed"] is None


@pytest.mark.asyncio
async def test_get_repos_branches_returns_parsed_branch_names():
    """GET /api/repos/{name}/branches parses git branch -a output into a list"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = os.path.join(tmpdir, "myrepo")
        os.makedirs(os.path.join(repo_dir, ".git"))

        git_output = "* main\n  feature/foo\n  remotes/origin/main\n  remotes/origin/HEAD -> origin/main\n"

        with patch("app.routes.repos.settings") as mock_settings, \
             patch("app.routes.repos.subprocess.run") as mock_run:

            mock_settings.source_dirs = tmpdir
            mock_process = MagicMock()
            mock_process.stdout = git_output
            mock_run.return_value = mock_process

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/repos/myrepo/branches")

    assert response.status_code == 200
    branches = response.json()
    assert "main" in branches
    assert "feature/foo" in branches
    assert "remotes/origin/main" in branches
    assert not any("->" in b for b in branches)


@pytest.mark.asyncio
async def test_get_repos_branches_returns_404_for_unknown_repo():
    """GET /api/repos/{name}/branches returns 404 when the repo name is not found"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("app.routes.repos.settings") as mock_settings:
            mock_settings.source_dirs = tmpdir

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/repos/nonexistent/branches")

    assert response.status_code == 404
