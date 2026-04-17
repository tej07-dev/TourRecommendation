# models/postgres_models.py - COMPLETE DATABASE MODELS (PostgreSQL Only)
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, ARRAY, JSON, Enum, Index, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime
import enum


Base = declarative_base()

# ============================================================================
# ENUMS
# ============================================================================

class GenderEnum(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"

class CrowdLevelEnum(str, enum.Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"

class CompanionTypeEnum(str, enum.Enum):
    SOLO = "solo"
    COUPLE = "couple"
    FAMILY = "family"
    FRIENDS = "friends"
    GROUP = "group"

class CategoryEnum(str, enum.Enum):
    HISTORICAL = "historical"
    NATURE = "nature"
    ADVENTURE = "adventure"
    RELIGIOUS = "religious"
    BEACH = "beach"
    MUSEUM = "museum"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    FOOD = "food"
    NIGHTLIFE = "nightlife"
    CULTURAL = "cultural"
    WELLNESS = "wellness"

class InteractionTypeEnum(str, enum.Enum):
    CLICK = "click"
    PREVIEW_VIEWED = "preview_viewed"
    ROUTE_REQUESTED = "route_requested"
    SAVE = "save"
    SKIP = "skip"
    SEARCH = "search"

# ============================================================================
# USER MODELS
# ============================================================================

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    
    # User profile for recommendations
    age = Column(Integer)
    gender = Column(Enum(GenderEnum))
    budget = Column(Float)  # Daily budget in local currency
    preferred_crowd_level = Column(Enum(CrowdLevelEnum))
    preferences = Column(ARRAY(String))  # Array of CategoryEnum values
    companion_type = Column(Enum(CompanionTypeEnum))
    # current_latitude = Column(Float)
    # current_longitude = Column(Float)
    # current_location = Column(Geography(geometry_type='POINT', srid=4326))

    
    # # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True, index=True)
    last_login = Column(DateTime)
    
    # Relationships
    user_preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")
    saved_places = relationship("SavedPlace", back_populates="user", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="user", cascade="all, delete-orphan")
    # __table_args__ = (


    #     Index('idx_user_location', 'current_location', postgresql_using='gist'),
    # )

class UserPreference(Base):
    """Additional user preferences beyond the main categories"""
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    preference_key = Column(String(100), nullable=False)
    preference_value = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="user_preferences")
    
    __table_args__ = (
        Index('idx_user_pref_key', 'user_id', 'preference_key'),
    )


# ============================================================================
# PLACE MODELS
# ============================================================================

class Place(Base):
    __tablename__ = "places"
    
    place_id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(255), unique=True, index=True)  # Google Place ID or other external ID
    name = Column(String(255), nullable=False, index=True)
    category = Column(Enum(CategoryEnum), nullable=False, index=True)
    subcategory = Column(String(100))
    
    # Location
    city = Column(String(100), nullable=False, index=True)
    state = Column(String(100))
    country = Column(String(100), default="India", index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location = Column(Geography(geometry_type='POINT', srid=4326), nullable=False)  # PostGIS spatial index
    
    # Details
    description = Column(Text)
    tags = Column(ARRAY(String))  # Keywords for TF-IDF
    
    # Metrics
    avg_cost = Column(Float)  # Average cost per person
    avg_rating = Column(Float, default=0.0, index=True)
    crowd_level = Column(Enum(CrowdLevelEnum))
    popularity_score = Column(Float, default=0.0, index=True)  # Computed from interactions
    
    # Attributes
    is_outdoor = Column(Boolean, default=False)
    opening_hours = Column(JSON)  # Store as JSON
    best_season = Column(ARRAY(String))  # ["winter", "summer", etc.]
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced = Column(DateTime)  # Last sync with external API
    
    # Relationships
    images = relationship("PlaceImage", back_populates="place", cascade="all, delete-orphan")
    saved_by = relationship("SavedPlace", back_populates="place", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="place", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_place_location', 'location', postgresql_using='gist'),
        Index('idx_place_category_rating', 'category', 'avg_rating'),
        Index('idx_place_city_category', 'city', 'category'),
    )


class PlaceImage(Base):
    __tablename__ = "place_images"
    
    image_id = Column(Integer, primary_key=True, autoincrement=True)
    place_id = Column(Integer, ForeignKey("places.place_id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500))
    caption = Column(String(255))
    is_primary = Column(Boolean, default=False)
    order = Column(Integer, default=0)
    source = Column(String(50))  # "google", "user_upload", etc.
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    place = relationship("Place", back_populates="images")


# ============================================================================
# INTERACTION MODELS (Replaced MongoDB)
# ============================================================================

class Interaction(Base):
    """
    User-place interactions (PostgreSQL)
    Optimized for fast inserts and time-based queries
    """
    __tablename__ = "interactions"
    
    interaction_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    place_id = Column(Integer, ForeignKey("places.place_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Interaction details
    interaction_type = Column(Enum(InteractionTypeEnum), nullable=False, index=True)
    session_id = Column(String(100), index=True)  # Track user sessions
    
    # Metadata
    interaction_context = Column(JSON)  # Store additional context (source, device, etc.)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="interactions")
    place = relationship("Place", back_populates="interactions")
    
    __table_args__ = (
        Index('idx_interaction_user_time', 'user_id', 'timestamp'),
        Index('idx_interaction_place_time', 'place_id', 'timestamp'),
        Index('idx_interaction_type_time', 'interaction_type', 'timestamp'),
        Index('idx_interaction_session', 'session_id', 'timestamp'),
        # Partial index for recent interactions (last 90 days) - commonly queried
        Index('idx_recent_interactions', 'user_id', 'timestamp', 
              postgresql_where=(Column('timestamp') >= datetime.utcnow())),
    )


class UserSession(Base):
    """Track user sessions for analytics"""
    __tablename__ = "user_sessions"
    
    session_id = Column(String(100), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Session details
    device_info = Column(JSON)  # Browser, OS, app version
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ended_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    __table_args__ = (
        Index('idx_session_user_time', 'user_id', 'started_at'),
    )


# ============================================================================
# SAVED PLACES
# ============================================================================

class SavedPlace(Base):
    __tablename__ = "saved_places"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    place_id = Column(Integer, ForeignKey("places.place_id", ondelete="CASCADE"), nullable=False, index=True)
    saved_at = Column(DateTime, default=datetime.utcnow, index=True)
    notes = Column(Text)
    
    # Relationships
    user = relationship("User", back_populates="saved_places")
    place = relationship("Place", back_populates="saved_by")
    
    __table_args__ = (
        Index('idx_saved_user_place', 'user_id', 'place_id', unique=True),
    )


# ============================================================================
# RECOMMENDATION LOGS
# ============================================================================

class RecommendationLog(Base):
    """Log recommendations served to users for evaluation and A/B testing"""
    __tablename__ = "recommendation_logs"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(String(100), unique=True, nullable=False, index=True)
    
    # Recommendations
    recommended_place_ids = Column(ARRAY(Integer))  # Ordered list of recommended place IDs
    scores = Column(JSON)  # {place_id: score}
    
    # Context
    model_version = Column(String(50), index=True)  # Track which model version
    location_type = Column(String(20))  # 'gps', 'city', 'none'
    location_context = Column(JSON)  # Store location info if provided
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_reclog_user_time', 'user_id', 'created_at'),
        Index('idx_reclog_model', 'model_version', 'created_at'),
    )


class SearchLog(Base):
    """Log user search queries"""
    __tablename__ = "search_logs"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    
    query = Column(String(500), nullable=False, index=True)
    filters = Column(JSON)  # Store filters applied
    results_count = Column(Integer)
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_search_user_time', 'user_id', 'timestamp'),
    )


# class Review(Base):
#     """User reviews and ratings for places"""
#     __tablename__ = "reviews"
    
#     review_id = Column(Integer, primary_key=True, index=True)
#     user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)
#     place_id = Column(Integer, ForeignKey('places.place_id'), nullable=False, index=True)
    
#     rating = Column(Float, nullable=False)
#     review_text = Column(Text)
    
#     # Metadata
#     created_at = Column(DateTime(timezone=True), server_default=func.now())
#     updated_at = Column(DateTime(timezone=True), onupdate=func.now())
#     is_verified = Column(Boolean, default=False)
#     helpful_count = Column(Integer, default=0)
    
#     # Relationships
#     user = relationship("User", back_populates="reviews")
#     place = relationship("Place", back_populates="reviews")
    
#     __table_args__ = (
#         Index('idx_review_user_place', 'user_id', 'place_id'),
#         Index('idx_review_rating', 'rating'),
#     )




class PrecomputedCandidate(Base):
    """Pre-computed candidate recommendations for users"""
    __tablename__ = "precomputed_candidates"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    place_id = Column(Integer, nullable=False)
    
    # Scores from different models
    ncf_score = Column(Float)
    content_score = Column(Float)
    combined_score = Column(Float, index=True)
    
    # Metadata
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        Index('idx_candidate_user_score', 'user_id', 'combined_score'),
    )

# ============================================================================
# MODEL METADATA
# ============================================================================

class ModelMetadata(Base):
    __tablename__ = "model_metadata"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    model_type = Column(String(50), nullable=False, index=True)  # "content_based", "collaborative", "ranking"
    model_version = Column(String(50), nullable=False)
    
    # Training info
    trained_at = Column(DateTime, default=datetime.utcnow, index=True)
    training_data_size = Column(Integer)
    training_duration_seconds = Column(Float)
    
    # Evaluation metrics (from evaluation layer)
    metrics = Column(JSON)  # Store all evaluation metrics
    
    # Model file
    is_active = Column(Boolean, default=True, index=True)
    file_path = Column(String(500))  # Path to serialized model
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)
    
    __table_args__ = (
        Index('idx_model_type_active', 'model_type', 'is_active'),
    )


# ============================================================================
# CACHE INVALIDATION TRACKING
# ============================================================================

class CacheInvalidation(Base):
    """Track what needs cache invalidation (for Redis)"""
    __tablename__ = "cache_invalidations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key_pattern = Column(String(200), nullable=False, index=True)
    reason = Column(String(100))
    invalidated_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Auto-cleanup old records
    __table_args__ = (
        Index('idx_cache_inv_time', 'invalidated_at'),
    )