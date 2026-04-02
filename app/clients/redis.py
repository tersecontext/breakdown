import json
import socket

import redis.asyncio as aioredis

COMPLEX_FIELDS = {"research", "additional_context", "optional_answers"}

_FRACTURE_STREAM = "stream:fracture-results"
_FRACTURE_GROUP = "breakdown"


class RedisQueue:
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)

    async def push_approved(self, bundle: dict) -> None:
        fields = {
            k: json.dumps(v) if k in COMPLEX_FIELDS else str(v)
            for k, v in bundle.items()
        }
        await self._redis.xadd("stream:breakdown-approved", fields)

    async def read_fracture_results(self):
        """Single-poll async generator. Yields (msg_id, decoded_fields) for each
        message returned by one xreadgroup call. Blocks up to 1 s for new messages.
        Caller loops and calls this repeatedly; caller is responsible for acking."""
        try:
            await self._redis.xgroup_create(
                _FRACTURE_STREAM, _FRACTURE_GROUP, id="0", mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        consumer = socket.gethostname()
        results = await self._redis.xreadgroup(
            _FRACTURE_GROUP,
            consumer,
            {_FRACTURE_STREAM: ">"},
            count=1,
            block=1000,
        )
        if not results:
            return
        for _stream, messages in results:
            for msg_id, fields in messages:
                decoded = {
                    (k.decode() if isinstance(k, bytes) else k): (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in fields.items()
                }
                yield msg_id, decoded

    async def ack_fracture_result(self, msg_id) -> None:
        await self._redis.xack(_FRACTURE_STREAM, _FRACTURE_GROUP, msg_id)

    async def close(self) -> None:
        await self._redis.aclose()
