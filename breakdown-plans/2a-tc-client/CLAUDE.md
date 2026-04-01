# Subtask 2a: TerseContext client

**Layer:** 2 (parallel — run alongside 2b and 2c after subtask 1 merges)
**Branch:** `feature/tc-client`
**Worktree:** `../breakdown-tc-client`

## Setup

```bash
cd breakdown
git worktree add -b feature/tc-client ../breakdown-tc-client
cp subtasks/2a-tc-client/CLAUDE.md ../breakdown-tc-client/SUBTASK.md
cd ../breakdown-tc-client
```

## What to build

HTTP client for querying TerseContext, plus the repos endpoint that uses it.

- Create `app/clients/tersecontext.py`:
  - Class `TerseContextClient` initialized with `base_url: str`
  - Uses `httpx.AsyncClient` internally
  - `async def query(self, query_text: str, repo: str | None = None) -> str`
    - POST to `{base_url}/query` with `{"query": query_text, "repo": repo}`
    - Return the context string from the response body
    - Timeout: 10s
    - Retries: 2 attempts with 1s backoff between
    - On failure after retries: raise `TerseContextError` with details
  - `async def health(self) -> dict | None`
    - GET `{base_url}/health`
    - Return JSON response or None if unreachable
  - `async def close(self)` — close the httpx client

- Create `app/routes/repos.py`:
  - `GET /api/repos` — scan each dir in `config.source_dirs.split(",")` for subdirs containing `.git`. For each repo return: `name` (dirname), `path` (full path), `tc_indexed` (bool from TC health check), `tc_node_count` (int or null), `tc_last_indexed` (str or null)
  - `GET /api/repos/{name}/branches` — subprocess `git -C {path} branch -a`, parse output, return list of branch name strings
  - Use TerseContextClient to check TC status per repo

- Register repos router in `app/main.py`

## Verify

```bash
# With TerseContext running:
python -c "
import asyncio
from app.clients.tersecontext import TerseContextClient
async def test():
    tc = TerseContextClient('http://localhost:8090')
    ctx = await tc.query('how does the parser work', 'tersecontext')
    print(f'Got {len(ctx)} chars')
    print(ctx[:200])
    await tc.close()
asyncio.run(test())
"

uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/api/repos
# expect: repos with tc_indexed status

curl http://localhost:8000/api/repos/tersecontext/branches
# expect: list of branch names
```

## Merge

```bash
cd ../breakdown
git merge feature/tc-client
git worktree remove ../breakdown-tc-client
```
