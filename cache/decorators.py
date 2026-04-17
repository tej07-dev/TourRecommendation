from functools import wraps
from .core_cache import cache


def cache_result(key_builder, ttl=None, serializer="json"):

    def decorator(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):

            cache_key = key_builder(*args, **kwargs)

            cached = await cache.get(cache_key, serializer=serializer)
            if cached is not None:
                return cached

            result = await func(*args, **kwargs)

            if result is not None:
                await cache.set(
                    cache_key,
                    result,
                    ttl=ttl,
                    serializer=serializer
                )

            return result

        return wrapper

    return decorator
