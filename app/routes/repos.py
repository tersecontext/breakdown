import os
import subprocess

from fastapi import APIRouter, HTTPException

from app.clients.tersecontext import TerseContextClient
from app.config import settings

router = APIRouter(prefix="/api/repos")


def _find_repos() -> list[dict]:
    repos = []
    for source_dir in settings.source_dirs.split(","):
        source_dir = source_dir.strip()
        if not os.path.isdir(source_dir):
            continue
        for entry in os.scandir(source_dir):
            if entry.is_dir() and os.path.isdir(os.path.join(entry.path, ".git")):
                repos.append({"name": entry.name, "path": entry.path})
    return repos


@router.get("")
async def get_repos():
    tc = TerseContextClient(settings.tersecontext_url)
    try:
        indexed = await tc.indexed_repos()
        repos = []
        for repo in _find_repos():
            tc_indexed = indexed is not None and repo["name"] in indexed
            repos.append({
                "name": repo["name"],
                "path": repo["path"],
                "tc_indexed": tc_indexed,
                "tc_node_count": None,
                "tc_last_indexed": None,
            })
        return repos
    finally:
        await tc.close()


@router.post("/{name}/index", status_code=202)
async def index_repo(name: str):
    repo = next((r for r in _find_repos() if r["name"] == name), None)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repo '{name}' not found")
    tc = TerseContextClient(settings.repo_watcher_url)
    try:
        result = await tc.index_repo(repo["path"], full_rescan=True)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Index request failed: {exc}")
    finally:
        await tc.close()


@router.get("/{name}/branches")
async def get_branches(name: str):
    repo = next((r for r in _find_repos() if r["name"] == name), None)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repo '{name}' not found")

    result = subprocess.run(
        ["git", "-C", repo["path"], "branch", "-a"],
        capture_output=True,
        text=True,
    )
    branches = []
    for line in result.stdout.splitlines():
        line = line.strip().lstrip("* ")
        if "->" not in line and line:
            branches.append(line)
    return branches
