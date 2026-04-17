# import redis.asyncio as redis
# from config.settings import get_settings
# import logging

# logger = logging.getLogger(__name__)


# class AsyncRedisClient:
#     """Singleton Async Redis Client (Production Ready)"""

#     _instance = None
#     _client: redis.Redis = None

#     def __new__(cls):
#         if cls._instance is None:
#             cls._instance = super().__new__(cls)
#         return cls._instance

#     async def connect(self):
#         if self._client is None:
#             settings = get_settings()

#             self._client = redis.Redis(
#                 host=settings.REDIS_HOST,
#                 port=settings.REDIS_PORT,
#                 db=settings.REDIS_DB,
#                 password=settings.REDIS_PASSWORD,
#                 decode_responses=False,
#                 socket_connect_timeout=5,
#                 socket_keepalive=True,
#                 max_connections=100
#             )

#             await self._client.ping()
#             logger.info("✅ Async Redis connected")

#     @property
#     def client(self):
#         return self._client

#     async def close(self):
#         if self._client:
#             await self._client.close()


# redis_client = AsyncRedisClient()

# cache/redis_client.py
import redis
import json
import pickle
from typing import Any, Optional, Union
from config.settings import get_settings
import logging

logger = logging.getLogger(__name__)
import sys 
from utils.exception import TourismRecommenderException
class RedisCache:
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            settings = get_settings()
            try:
                self._client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=settings.REDIS_PASSWORD,
                    decode_responses=False,  # We'll handle encoding/decoding
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    max_connections=50
                )
                # Test connection
                self._client.ping()
                logger.info("Redis connection established")
            except redis.ConnectionError as e:
                logger.error(f"Redis connection failed: {e}")
                raise TourismRecommenderException(e,sys)
    
    @property
    def client(self):
        return self._client
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        serializer: str = "json"
    ) -> bool:
        """
        Set a value in cache
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
            serializer: "json" or "pickle"
        """
        try:
            if serializer == "json":
                serialized_value = json.dumps(value)
            elif serializer == "pickle":
                serialized_value = pickle.dumps(value)
            else:
                raise ValueError(f"Unknown serializer: {serializer}")
            
            if ttl:
                return self._client.setex(key, ttl, serialized_value)
            else:
                return self._client.set(key, serialized_value)
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")
            return False
    
    def get(
        self,
        key: str,
        serializer: str = "json"
    ) -> Optional[Any]:
        """
        Get a value from cache
        
        Args:
            key: Cache key
            serializer: "json" or "pickle"
        """
        try:
            value = self._client.get(key)
            if value is None:
                return None
            
            if serializer == "json":
                return json.loads(value)
            elif serializer == "pickle":
                return pickle.loads(value)
            else:
                raise ValueError(f"Unknown serializer: {serializer}")
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete a key from cache"""
        try:
            return self._client.delete(key) > 0
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            return self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Error checking cache key {key}: {e}")
            return False
    
    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment a counter"""
        try:
            return self._client.incrby(key, amount)
        except Exception as e:
            logger.error(f"Error incrementing cache key {key}: {e}")
            return None
    
    def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on a key"""
        try:
            return self._client.expire(key, ttl)
        except Exception as e:
            logger.error(f"Error setting expiration on key {key}: {e}")
            return False
    
    def get_many(self, keys: list, serializer: str = "json") -> dict:
        """Get multiple keys at once"""
        try:
            values = self._client.mget(keys)
            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    if serializer == "json":
                        result[key] = json.loads(value)
                    elif serializer == "pickle":
                        result[key] = pickle.loads(value)
            return result
        except Exception as e:
            logger.error(f"Error getting multiple cache keys: {e}")
            return {}
    
    def set_many(self, mapping: dict, ttl: Optional[int] = None, serializer: str = "json"):
        """Set multiple keys at once"""
        try:
            pipe = self._client.pipeline()
            for key, value in mapping.items():
                if serializer == "json":
                    serialized_value = json.dumps(value)
                elif serializer == "pickle":
                    serialized_value = pickle.dumps(value)
                else:
                    raise ValueError(f"Unknown serializer: {serializer}")
                
                if ttl:
                    pipe.setex(key, ttl, serialized_value)
                else:
                    pipe.set(key, serialized_value)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Error setting multiple cache keys: {e}")
            return False
    
    def flush_db(self):
        """Flush all keys in current database (use with caution!)"""
        try:
            return self._client.flushdb()
        except Exception as e:
            logger.error(f"Error flushing database: {e}")
            return False


# Singleton instance
redis_cache = RedisCache()


# Cache key builders
class CacheKeys:
    """Centralized cache key management"""
    
    @staticmethod
    def user_recommendations(user_id: int) -> str:
        return f"recommendations:user:{user_id}"
    
    @staticmethod
    def place_details(place_id: int) -> str:
        return f"place:details:{place_id}"
    
    @staticmethod
    def place_images(place_id: int) -> str:
        return f"place:images:{place_id}"
    
    @staticmethod
    def youtube_preview(place_id: int) -> str:
        return f"youtube:preview:{place_id}"
    
    @staticmethod
    def weather_data(place_id: int) -> str:
        return f"weather:place:{place_id}"
    
    @staticmethod
    def popular_places(category: Optional[str] = None) -> str:
        if category:
            return f"popular:places:{category}"
        return "popular:places:all"
    
    @staticmethod
    def user_profile(user_id: int) -> str:
        return f"user:profile:{user_id}"
    
    @staticmethod
    def rate_limit(user_id: int, window: str) -> str:
        """window can be 'minute' or 'hour'"""
        return f"rate_limit:{window}:user:{user_id}"
    
    @staticmethod
    def model_version(model_type: str) -> str:
        return f"model:version:{model_type}"
    
    @staticmethod
    def tfidf_matrix() -> str:
        return "model:tfidf:matrix"
    
    @staticmethod
    def als_model() -> str:
        return "model:als:collaborative"
    
    @staticmethod
    def ranking_model() -> str:
        return "model:ranking:lgbm"
    
    @staticmethod
    def place_embeddings() -> str:
        return "model:embeddings:places"
    
    @staticmethod
    def nearby_places(lat: float, lon: float, radius_km: float) -> str:
        return f"nearby:{lat:.4f}:{lon:.4f}:{radius_km}"


# Decorators for caching
from functools import wraps

def cache_result(key_builder, ttl: Optional[int] = None, serializer: str = "json"):
    """Decorator to cache function results"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Build cache key
            cache_key = key_builder(*args, **kwargs)
            
            # Try to get from cache
            cached_value = redis_cache.get(cache_key, serializer=serializer)
            if cached_value is not None:
                logger.debug(f"Cache hit for key: {cache_key}")
                return cached_value
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            if result is not None:
                redis_cache.set(cache_key, result, ttl=ttl, serializer=serializer)
                logger.debug(f"Cached result for key: {cache_key}")
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = key_builder(*args, **kwargs)
            
            cached_value = redis_cache.get(cache_key, serializer=serializer)
            if cached_value is not None:
                logger.debug(f"Cache hit for key: {cache_key}")
                return cached_value
            
            result = func(*args, **kwargs)
            
            if result is not None:
                redis_cache.set(cache_key, result, ttl=ttl, serializer=serializer)
                logger.debug(f"Cached result for key: {cache_key}")
            
            return result
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator