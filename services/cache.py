import redis.asyncio as aioredis
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from config.settings import get_settings
import pickle
import hashlib

settings = get_settings()


class RedisCache:
    """Redis caching service for recommendation system"""
    
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
    
    async def connect(self):
        """Connect to Redis"""
        self.redis_client = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=False  # We'll handle encoding ourselves
        )
    
    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from prefix and arguments"""
        # Create a unique key from arguments
        key_parts = [prefix]
        
        for arg in args:
            key_parts.append(str(arg))
        
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{v}")
        
        return ":".join(key_parts)
    
    def _hash_key(self, data: Dict) -> str:
        """Create hash from dictionary for cache key"""
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.md5(serialized.encode()).hexdigest()
    
    # Precomputed Candidates Cache
    async def cache_user_candidates(
        self,
        user_id: int,
        candidates: List[Dict],
        ttl: int = None
    ):
        """Cache pre-computed candidates for a user"""
        if ttl is None:
            ttl = settings.CACHE_TTL_CANDIDATES
        
        key = f"candidates:user:{user_id}"
        value = pickle.dumps(candidates)
        
        await self.redis_client.setex(key, ttl, value)
    
    async def get_user_candidates(self, user_id: int) -> Optional[List[Dict]]:
        """Get cached candidates for a user"""
        key = f"candidates:user:{user_id}"
        value = await self.redis_client.get(key)
        
        if value:
            return pickle.loads(value)
        return None
    
    async def invalidate_user_candidates(self, user_id: int):
        """Invalidate cached candidates for a user"""
        key = f"candidates:user:{user_id}"
        await self.redis_client.delete(key)
    
    # Final Recommendations Cache
    async def cache_recommendations(
        self,
        user_id: int,
        request_params: Dict,
        recommendations: List[Dict],
        ttl: int = None
    ):
        """Cache final ranked recommendations"""
        if ttl is None:
            ttl = settings.CACHE_TTL_RECOMMENDATIONS
        
        params_hash = self._hash_key(request_params)
        key = f"recommendations:user:{user_id}:params:{params_hash}"
        
        cache_data = {
            'recommendations': recommendations,
            'cached_at': datetime.now().isoformat(),
            'request_params': request_params
        }
        
        value = pickle.dumps(cache_data)
        await self.redis_client.setex(key, ttl, value)
    
    async def get_recommendations(
        self,
        user_id: int,
        request_params: Dict
    ) -> Optional[Dict]:
        """Get cached recommendations"""
        params_hash = self._hash_key(request_params)
        key = f"recommendations:user:{user_id}:params:{params_hash}"
        
        value = await self.redis_client.get(key)
        
        if value:
            return pickle.loads(value)
        return None
    
    # YouTube Videos Cache
    async def cache_youtube_videos(
        self,
        place_id: int,
        videos: List[Dict],
        ttl: int = None
    ):
        """Cache YouTube videos for a place"""
        if ttl is None:
            ttl = settings.CACHE_TTL_VIDEOS
        
        key = f"youtube:place:{place_id}"
        value = json.dumps(videos, default=str)
        
        await self.redis_client.setex(key, ttl, value)
    
    async def get_youtube_videos(self, place_id: int) -> Optional[List[Dict]]:
        """Get cached YouTube videos"""
        key = f"youtube:place:{place_id}"
        value = await self.redis_client.get(key)
        
        if value:
            return json.loads(value)
        return None
    
    # Weather Cache
    async def cache_weather(
        self,
        place_id: int,
        weather_data: Dict,
        ttl: int = None
    ):
        """Cache weather data for a place"""
        if ttl is None:
            ttl = settings.CACHE_TTL_WEATHER
        
        key = f"weather:place:{place_id}"
        value = json.dumps(weather_data, default=str)
        
        await self.redis_client.setex(key, ttl, value)
    
    async def get_weather(self, place_id: int) -> Optional[Dict]:
        """Get cached weather data"""
        key = f"weather:place:{place_id}"
        value = await self.redis_client.get(key)
        
        if value:
            return json.loads(value)
        return None
    
    # Route Cache
    async def cache_route(
        self,
        waypoints_hash: str,
        route_data: Dict,
        ttl: int = 86400  # 24 hours for routes
    ):
        """Cache route data"""
        key = f"route:{waypoints_hash}"
        value = json.dumps(route_data, default=str)
        
        await self.redis_client.setex(key, ttl, value)
    
    async def get_route(self, waypoints_hash: str) -> Optional[Dict]:
        """Get cached route data"""
        key = f"route:{waypoints_hash}"
        value = await self.redis_client.get(key)
        
        if value:
            return json.loads(value)
        return None
    
    # Model Embeddings Cache (for faster inference)
    async def cache_user_embedding(
        self,
        user_id: int,
        embedding: Any,
        ttl: int = 3600
    ):
        """Cache user embedding from NCF model"""
        key = f"embedding:user:{user_id}"
        value = pickle.dumps(embedding)
        
        await self.redis_client.setex(key, ttl, value)
    
    async def get_user_embedding(self, user_id: int) -> Optional[Any]:
        """Get cached user embedding"""
        key = f"embedding:user:{user_id}"
        value = await self.redis_client.get(key)
        
        if value:
            return pickle.loads(value)
        return None
    
    async def cache_place_embedding(
        self,
        place_id: int,
        embedding: Any,
        ttl: int = 86400
    ):
        """Cache place embedding"""
        key = f"embedding:place:{place_id}"
        value = pickle.dumps(embedding)
        
        await self.redis_client.setex(key, ttl, value)
    
    async def get_place_embedding(self, place_id: int) -> Optional[Any]:
        """Get cached place embedding"""
        key = f"embedding:place:{place_id}"
        value = await self.redis_client.get(key)
        
        if value:
            return pickle.loads(value)
        return None
    
    # Batch Operations
    async def cache_multiple(
        self,
        items: List[tuple],  # List of (key, value, ttl)
    ):
        """Cache multiple items in batch"""
        pipeline = self.redis_client.pipeline()
        
        for key, value, ttl in items:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str)
            elif not isinstance(value, (str, bytes)):
                value = pickle.dumps(value)
            
            pipeline.setex(key, ttl, value)
        
        await pipeline.execute()
    
    async def get_multiple(
        self,
        keys: List[str],
        deserialize_json: bool = True
    ) -> List[Optional[Any]]:
        """Get multiple cached items"""
        values = await self.redis_client.mget(keys)
        
        results = []
        for value in values:
            if value is None:
                results.append(None)
            elif deserialize_json:
                try:
                    results.append(json.loads(value))
                except:
                    results.append(pickle.loads(value))
            else:
                results.append(value)
        
        return results
    
    # Statistics and Monitoring
    async def increment_counter(self, key: str, amount: int = 1):
        """Increment a counter"""
        return await self.redis_client.incrby(key, amount)
    
    async def get_counter(self, key: str) -> int:
        """Get counter value"""
        value = await self.redis_client.get(key)
        return int(value) if value else 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        info = await self.redis_client.info('stats')
        
        return {
            'total_keys': await self.redis_client.dbsize(),
            'hits': info.get('keyspace_hits', 0),
            'misses': info.get('keyspace_misses', 0),
            'hit_rate': info.get('keyspace_hits', 0) / 
                       max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0), 1)
        }
    
    # Cleanup Operations
    async def clear_user_cache(self, user_id: int):
        """Clear all cache for a specific user"""
        patterns = [
            f"candidates:user:{user_id}",
            f"recommendations:user:{user_id}:*",
            f"embedding:user:{user_id}"
        ]
        
        for pattern in patterns:
            keys = await self.redis_client.keys(pattern)
            if keys:
                await self.redis_client.delete(*keys)
    
    async def clear_all_cache(self):
        """Clear all cache (use with caution!)"""
        await self.redis_client.flushdb()


# Global cache instance
cache = RedisCache()


async def get_cache() -> RedisCache:
    """Dependency for getting cache instance"""
    return cache