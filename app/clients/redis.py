import json

import redis.asyncio as aioredis

COMPLEX_FIELDS = {"research", "additional_context", "optional_answers"}


class RedisQueue:
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)

    async def push_approved(self, bundle: dict) -> None:
        fields = {
            k: json.dumps(v) if k in COMPLEX_FIELDS else str(v)
            for k, v in bundle.items()
        }
        await self._redis.xadd("stream:breakdown-approved", fields)

    async def close(self) -> None:
        await self._redis.aclose()
