from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd

from database_models.postgres_model import Interaction, InteractionTypeEnum, Place
from database.connection import get_db_context

class InteractionRepository:
    """
    PostgreSQL-based interaction repository.
    
    STANDARDIZED: Single implementations of all methods.
    Uses interaction_type.value everywhere (string value, not enum).
    Shared INTERACTION_WEIGHTS from settings.
    """
    
    @staticmethod
    def get_all_interactions(db: Session) -> pd.DataFrame:
        """
        Get all interactions as DataFrame for model training.
        
        Args:
            db: Database session
            
        Returns:
            DataFrame with columns: user_id, place_id, interaction_type, timestamp
        """
        interactions = db.query(Interaction).all()
        
        if not interactions:
            return pd.DataFrame(columns=['user_id', 'place_id', 'interaction_type', 'timestamp'])
        
        return pd.DataFrame([{
            'user_id': i.user_id,
            'place_id': i.place_id,
            'interaction_type': i.interaction_type.value if hasattr(i.interaction_type, 'value') else i.interaction_type,
            'timestamp': i.timestamp
        } for i in interactions])
    
    @staticmethod
    def get_user_history(
        db: Session, 
        user_id: int, 
        days: int = 90,
        interaction_types: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get user's interaction history.
        
        Args:
            db: Database session
            user_id: User ID
            days: Number of days to look back
            interaction_types: Optional filter for specific interaction types
            
        Returns:
            List of interaction dicts with standardized interaction_type (string value)
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        query = db.query(Interaction).filter(
            Interaction.user_id == user_id,
            Interaction.timestamp >= cutoff_date
        )
        
        if interaction_types:
            query = query.filter(Interaction.interaction_type.in_(interaction_types))
        
        interactions = query.order_by(Interaction.timestamp.desc()).all()
        
        return [{
            'user_id': i.user_id,
            'place_id': i.place_id,
            'interaction_type': i.interaction_type.value if hasattr(i.interaction_type, 'value') else i.interaction_type,
            'timestamp': i.timestamp,
            'metadata': i.metadata or {}
        } for i in interactions]
    
    @staticmethod
    def get_popular_places(
        db: Session, 
        limit: int = 50,
        days: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Get popular places based on interaction count.
        
        Args:
            db: Database session
            limit: Maximum number of places to return
            days: Optional - only count interactions from last N days
            
        Returns:
            List of (place_id, popularity_score) tuples
        """
        # Only count positive interactions
        positive_types = [
            InteractionTypeEnum.SAVE,
            InteractionTypeEnum.ROUTE_REQUESTED,
            InteractionTypeEnum.PREVIEW_VIEWED,
            InteractionTypeEnum.CLICK
        ]
        
        query = db.query(
            Interaction.place_id,
            func.count(Interaction.interaction_id).label('interaction_count'),
            func.count(func.distinct(Interaction.user_id)).label('unique_users')
        ).filter(
            Interaction.interaction_type.in_(positive_types)
        )
        
        # Filter by date if specified
        if days:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Interaction.timestamp >= cutoff_date)
        
        popular = query.group_by(
            Interaction.place_id
        ).order_by(
            desc('interaction_count')
        ).limit(limit).all()
        
        # Return as (place_id, score) tuples where score combines counts
        return [
            (p.place_id, float(p.interaction_count + p.unique_users * 0.5))
            for p in popular
        ]
    
    @staticmethod
    def get_user_interacted_places(
        db: Session,
        user_id: int,
        interaction_types: Optional[List[str]] = None
    ) -> List[int]:
        """
        Get list of place IDs the user has interacted with.
        
        Args:
            db: Database session
            user_id: User ID
            interaction_types: Optional filter for specific interaction types
            
        Returns:
            List of place IDs
        """
        query = db.query(Interaction.place_id).filter(
            Interaction.user_id == user_id
        )
        
        if interaction_types:
            query = query.filter(Interaction.interaction_type.in_(interaction_types))
        
        results = query.distinct().all()
        return [r[0] for r in results]
    
    @staticmethod
    def create_interaction(
        db: Session,
        user_id: int,
        place_id: int,
        interaction_type: str,
        metadata: Optional[Dict] = None
    ) -> Interaction:
        """
        Create a new interaction record.
        
        Args:
            db: Database session
            user_id: User ID
            place_id: Place ID
            interaction_type: Type of interaction (string value)
            metadata: Optional additional metadata
            
        Returns:
            Created Interaction object
        """
        interaction = Interaction(
            user_id=user_id,
            place_id=place_id,
            interaction_type=interaction_type,
            metadata=metadata or {},
            timestamp=datetime.utcnow()
        )
        
        db.add(interaction)
        db.commit()
        db.refresh(interaction)
        
        return interaction
    
    @staticmethod
    def batch_create_interactions(
        db: Session,
        interactions: List[Dict]
    ) -> int:
        """
        Bulk create multiple interactions.
        
        Args:
            db: Database session
            interactions: List of interaction dicts with keys:
                         user_id, place_id, interaction_type, metadata (optional)
            
        Returns:
            Number of interactions created
        """
        interaction_objects = []
        
        for interaction_data in interactions:
            interaction = Interaction(
                user_id=interaction_data['user_id'],
                place_id=interaction_data['place_id'],
                interaction_type=interaction_data['interaction_type'],
                metadata=interaction_data.get('metadata', {}),
                timestamp=interaction_data.get('timestamp', datetime.utcnow())
            )
            interaction_objects.append(interaction)
        
        db.bulk_save_objects(interaction_objects)
        db.commit()
        
        return len(interaction_objects)
    
    @staticmethod
    def get_category_affinity(
        db: Session,
        user_id: int,
        days: int = 180
    ) -> Dict[str, float]:
        """
        Calculate user's affinity for different categories based on interactions.
        Uses shared INTERACTION_WEIGHTS from settings.
        
        Args:
            db: Database session
            user_id: User ID
            days: Number of days to consider
            
        Returns:
            Dict mapping category to affinity score (0-1)
        """
        from config.settings import get_settings
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        settings = get_settings()
        
        # Join interactions with places to get categories
        interactions = db.query(
            Place.category,
            Interaction.interaction_type,
            func.count(Interaction.interaction_id).label('count')
        ).join(
            Interaction,
            Interaction.place_id == Place.place_id
        ).filter(
            Interaction.user_id == user_id,
            Interaction.timestamp >= cutoff_date
        ).group_by(
            Place.category,
            Interaction.interaction_type
        ).all()
        
        if not interactions:
            return {}
        
        # Calculate weighted scores per category
        category_scores = {}
        for category, interaction_type, count in interactions:
            # Normalize interaction_type to string value
            itype_value = interaction_type.value if hasattr(interaction_type, 'value') else interaction_type
            weight = settings.INTERACTION_WEIGHTS.get(itype_value, 1.0)
            category_scores[category] = category_scores.get(category, 0.0) + (count * weight)
        
        # Normalize to 0-1 range
        if category_scores:
            max_score = max(category_scores.values())
            if max_score > 0:
                category_scores = {
                    cat: score / max_score 
                    for cat, score in category_scores.items()
                }
        
        return category_scores
    
    @staticmethod
    def get_interaction_stats(
        db: Session,
        user_id: Optional[int] = None,
        place_id: Optional[int] = None
    ) -> Dict:
        """
        Get interaction statistics.
        
        Args:
            db: Database session
            user_id: Optional user ID
            place_id: Optional place ID
            
        Returns:
            Dict with interaction statistics
        """
        query = db.query(Interaction)
        
        if user_id:
            query = query.filter(Interaction.user_id == user_id)
        if place_id:
            query = query.filter(Interaction.place_id == place_id)
        
        interactions = query.all()
        
        if not interactions:
            return {
                'total_interactions': 0,
                'interaction_types': {},
                'first_interaction': None,
                'last_interaction': None
            }
        
        # Count by type
        type_counts = {}
        for i in interactions:
            itype_value = i.interaction_type.value if hasattr(i.interaction_type, 'value') else i.interaction_type
            type_counts[itype_value] = type_counts.get(itype_value, 0) + 1
        
        # Get timestamps
        timestamps = [i.timestamp for i in interactions]
        
        return {
            'total_interactions': len(interactions),
            'interaction_types': type_counts,
            'first_interaction': min(timestamps),
            'last_interaction': max(timestamps),
        }


