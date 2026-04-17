from .core_cache import cache
from .keys import CacheKeys


class RecommendationCache:

    async def cache_candidates(self, user_id, candidates, ttl):
        await cache.set(
            CacheKeys.candidates(user_id),
            candidates,
            ttl=ttl,
            serializer="pickle"
        )

    async def get_candidates(self, user_id):
        return await cache.get(
            CacheKeys.candidates(user_id),
            serializer="pickle"
        )

    async def cache_ranked(self, user_id, params, results, ttl):
        await cache.set(
            CacheKeys.recommendations(user_id, params),
            results,
            ttl=ttl,
            serializer="pickle"
        )

    async def get_ranked(self, user_id, params):
        return await cache.get(
            CacheKeys.recommendations(user_id, params),
            serializer="pickle"
        )

    async def clear_user(self, user_id):
        await cache.scan_delete(f"rec:*:user:{user_id}*")


recommendation_cache = RecommendationCache()
