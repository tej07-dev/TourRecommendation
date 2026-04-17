import json
import pickle
from typing import Any, Optional
from .redis_client import redis_client


class AsyncCache:

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        serializer: str = "json"
    ):

        client = redis_client.client

        if serializer == "json":
            value = json.dumps(value)
        elif serializer == "pickle":
            value = pickle.dumps(value)

        if ttl:
            await client.setex(key, ttl, value)
        else:
            await client.set(key, value)

    async def get(
        self,
        key: str,
        serializer: str = "json"
    ) -> Optional[Any]:

        client = redis_client.client
        value = await client.get(key)

        if value is None:
            return None

        if serializer == "json":
            return json.loads(value)
        elif serializer == "pickle":
            return pickle.loads(value)

    async def delete(self, key: str):
        await redis_client.client.delete(key)

    async def exists(self, key: str) -> bool:
        return await redis_client.client.exists(key) > 0

    async def scan_delete(self, pattern: str):
        """Safe delete (no KEYS usage)"""
        async for key in redis_client.client.scan_iter(pattern):
            await redis_client.client.delete(key)


cache = AsyncCache()
