import asyncio
import httpx


class TerseContextError(Exception):
    pass


class TerseContextClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def query(self, query_text: str, repo: str | None = None) -> str:
        last_exc = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(1)
            try:
                response = await self._client.post(
                    f"{self.base_url}/query",
                    json={"question": query_text, "repo": repo},
                )
                response.raise_for_status()
                return response.text
            except Exception as e:
                last_exc = e
        raise TerseContextError(f"TerseContext query failed after 3 attempts: {last_exc}")

    async def health(self) -> dict | None:
        try:
            response = await self._client.get(f"{self.base_url}/health")
            return response.json()
        except Exception:
            return None

    async def indexed_repos(self) -> list[str] | None:
        try:
            response = await self._client.get(f"{self.base_url}/repos")
            return response.json()
        except Exception:
            return None

    async def repo_status(self, name: str) -> dict | None:
        try:
            response = await self._client.get(f"{self.base_url}/repos/{name}/status")
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    async def index_repo(self, repo_path: str, full_rescan: bool = False) -> dict:
        response = await self._client.post(
            f"{self.base_url}/index",
            json={"repo_path": repo_path, "full_rescan": full_rescan},
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self._client.aclose()
