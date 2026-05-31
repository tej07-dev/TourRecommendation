# config/settings.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional,Dict
import os
class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Tourism Recommendation System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "tourism_db1"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD")
    
    @property
    def POSTGRES_URI(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_CACHE_TTL: int = 3600  # 1 hour
    
    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    CACHE_TTL_CANDIDATES: int = 3600  # 1 hour for pre-computed candidates
    CACHE_TTL_RECOMMENDATIONS: int = 300  # 5 minutes for final recommendations
    CACHE_TTL_WEATHER: int = 1800  # 30 minutes for weather
    CACHE_TTL_VIDEOS: int = 86400  # 24 hours for YouTube videos

    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # External APIs
    GOOGLE_PLACES_API_KEY: str = ""
    YOUTUBE_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""
    YOUTUBE_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = "YOUR_OPENWEATHER_API_KEY"
    
    # YouTube Settings
    YOUTUBE_MAX_RESULTS: int = 5
    YOUTUBE_SEARCH_RADIUS: int = 50  # km around place
    
    # OpenWeatherMap Settings
    OPENWEATHER_UNITS: str = "metric"
    WEATHER_ALERT_TYPES: list = ["warning", "watch", "advisory"]
    
    # OpenStreetMap Settings
    OSM_API_URL: str = "https://router.project-osrm.org/routed-bike/route/v1"
    OSM_PROFILE: str = "car"  # car, bike, foot
    
    # Route Optimization
    ROUTE_MAX_DESTINATIONS: int = 10
    ROUTE_SCENIC_WEIGHT: float = 0.4  # Weight for scenic routes
    ROUTE_POPULARITY_WEIGHT: float = 0.2  # Weight for popular sequences
    ROUTE_DISTANCE_WEIGHT: float = 0.3  # Weight for distance optimization
    ROUTE_DURATION_WEIGHT:float = 0.1
    

    # ML Model Settings
    MODEL_UPDATE_INTERVAL_HOURS: int = 1  # Batch processing interval
    MODEL_RETRAIN_INTERVAL_DAYS: int = 1
    RECOMMENDATION_CACHE_TTL: int = 3600  # 1 hour
    
    # Recommendation Parameters
    MAX_RECOMMENDATIONS: int = 20
    CANDIDATE_POOL_SIZE: int = 200
    DISTANCE_THRESHOLD_KM: float = 50.0
    DIVERSITY_WEIGHT: float = 0.3
    FRESHNESS_DECAY_DAYS: int = 30
    
    # Content-Based Filtering
    TFIDF_MAX_FEATURES: int = 500
    COSINE_SIMILARITY_THRESHOLD: float = 0.1
    INTERACTION_WEIGHTS : Dict[str, float] = {
    
        'save': 5.0,
        'route_requested': 4.0,
        'preview_viewed': 3.0,
        'click': 2.0,
        'search': 1.0,
        'skip': 0.0  # Negative signal
    }

    ALS_CONFIDENCE_ALPHA: float = 40.0
    ALS_RECENCY_HALF_LIFE_DAYS: int = 30
   
    # Collaborative Filtering
    ALS_FACTORS: int = 50
    ALS_REGULARIZATION: float = 0.01
    ALS_ITERATIONS: int = 15
    ALS_ALPHA: float = 40.0
    
    # Ranking Model
    RANKING_MODEL_TYPE: str = "lightgbm"  # or "neural_network"
    # LGBM_NUM_LEAVES: int = 31
    # LGBM_LEARNING_RATE: float = 0.05
    # LGBM_N_ESTIMATORS: int = 100
    
    LAMBDARANK_LEARNING_RATE: float = 0.01
    LAMBDARANK_N_ESTIMATORS: int = 100
    LAMBDARANK_MAX_DEPTH: int = 6
    

    # Cold Start
    COLD_START_POPULAR_COUNT: int = 10
    COLD_START_LOCATION_RADIUS_KM: float = 20.0
    
    # Weather Alerts
    WEATHER_CHECK_HOURS_AHEAD: int = 24
    WEATHER_ALERT_THRESHOLD_RAIN_MM: float = 5.0
    WEATHER_ALERT_THRESHOLD_TEMP_HIGH: float = 40.0
    WEATHER_ALERT_THRESHOLD_TEMP_LOW: float = 0.0
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    
    
    
    # Model Paths (update)
    ALS_MODEL_PATH: str = "models/als_model.pkl"
    CONTENT_MODEL_PATH: str = "models/content_based_model.pkl"
    LAMBDARANK_MODEL_PATH: str ="models/lambda_rank_model.txt"
    MODEL_DIR: str = "models"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    return Settings()
