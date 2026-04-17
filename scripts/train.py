"""
Training script for ML models

This script trains all recommendation models:
1. Neural Collaborative Filtering (NCF)
2. Content-Based Filter
3. LambdaRank

Usage:
    python scripts/train_models.py
"""

import asyncio

from datetime import datetime


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import get_settings
from database_models.postgres_model import User, Place, Interaction
from ml.collaborative import CollaborativeFilteringRecommender
from ml.content_based import ContentBasedRecommender
from ml.ranker import LambdaRankModel

settings = get_settings()

def train_collaborative_filtering(interactions_df):
    """Train ALS model"""
    print("\n" + "="*50)
    print("Training Collaborative Filtering (ALS)")
    print("="*50)
    
    cf_model = CollaborativeFilteringRecommender()
    cf_model.fit(interactions_df)
    
    # Save
    print(f"\nSaving to {settings.ALS_MODEL_PATH}")
    cf_model.save_model(settings.ALS_MODEL_PATH)
    
    return cf_model

def train_content_based(places_df):
    """Train Content-Based Filter"""
    print("\n" + "="*50)
    print("Training Content-Based Filter")
    print("="*50)
    
    content_model = ContentBasedRecommender()
    content_model.fit(places_df)
    
    # Save
    print(f"\nSaving to {settings.CONTENT_MODEL_PATH}")
    content_model.save_model(settings.CONTENT_MODEL_PATH)
    
    return content_model


import numpy as np

def train_lambdarank(interactions_data, users_data, places_data, settings):
    """
    Train LambdaRank model using grouped session data.
    """
    print("\n" + "="*50)
    print("Training LambdaRank Model")
    print("="*50)
    
    # 1. Map data for quick lookup
    users_dict = {u['user_id']: u for u in users_data}
    places_dict = {p['place_id']: p for p in places_data}
    
    # 2. Group interactions by User to create "Sessions"
    # LambdaRank needs to compare items for the SAME user
    user_sessions = {}
    for interaction in interactions_data:
        u_id = interaction['user_id']
        p_id = interaction['place_id']
        
        if u_id not in users_dict or p_id not in places_dict:
            continue
            
        if u_id not in user_sessions:
            user_sessions[u_id] = {
                "user_features": {
                    'age': users_dict[u_id].get('age', 30),
                    # 'budget': users_dict[u_id].get('budget', 'medium'),
                    'companion_type': users_dict[u_id].get('companion_type', 'solo'),
                    # 'preferred_crowd_level': users_dict[u_id].get('preferred_crowd_level', 'moderate'),
                    'preferences': users_dict[u_id].get('preferences', [])
                },
                "items": []
            }
        
        # Calculate relevance (e.g., click=1, favorite=2, review=3)
        # Note: Ensure this function is imported or defined
        lamdarank=LambdaRankModel()
        relevance = lamdarank.calculate_relevance_from_interactions(
            interaction['interaction_type']
        )
        
        user_sessions[u_id]["items"].append({
            'place_id': p_id,
            'place_features': {
                'category': places_dict[p_id].get('category', ''),
                'tags': places_dict[p_id].get('tags', []),
                # 'avg_cost': places_dict[p_id].get('avg_cost', 0),
                'avg_rating': places_dict[p_id].get('avg_rating', 0),
                # 'crowd_level': places_dict[p_id].get('crowd_level', 'moderate'),
                'popularity_score': places_dict[p_id].get('popularity_score', 0)
            },
            'ncf_score': interaction.get('ncf_score', 0.5), # Use actual scores if available
            'content_score': interaction.get('content_score', 0.5),
            'relevance_level': relevance,
            'context_features': interaction.get('context', {})
        })

    # 3. Convert dict to list of sessions for the model
    # Filter out sessions with only 1 item (Rankers need >1 to learn preferences)
    grouped_samples = [s for s in user_sessions.values() if len(s['items']) > 1]
    
    print(f"Training on {len(grouped_samples)} user sessions...")
    
    # 4. Initialize and train using the RealLambdaRankModel class
    ranker = LambdaRankModel(
        learning_rate=settings.LAMBDARANK_LEARNING_RATE,
        n_estimators=settings.LAMBDARANK_N_ESTIMATORS,
        num_leaves=31 # or map from settings
    )
    
    feature_importances = ranker.fit(grouped_samples)
    
    # 5. Output Results
    print("\nFeature Importances (Gain):")
    for feature, importance in sorted(
        feature_importances.items(),
        key=lambda x: x[1],
        reverse=True
    ):
        print(f"  {feature}: {importance:.4f}")
    
    # 6. Save
    print(f"\nSaving to {settings.LAMBDARANK_MODEL_PATH}")
    ranker.save(settings.LAMBDARANK_MODEL_PATH)
    
    return ranker

def main():
    print("="*50)
    print("ML Model Training Pipeline")
    print("="*50)
    
    Path(settings.MODEL_DIR).mkdir(parents=True, exist_ok=True)
    
    # Connect to database
    engine = create_engine(settings.SYNC_DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    print("\nLoading data from database...")
    
    # Load interactions
    interactions = session.query(Interaction).all()
    interactions_df = pd.DataFrame([
        {
            'user_id': i.user_id,
            'place_id': i.place_id,
            'interaction_type': i.interaction_type.value,
            'timestamp': i.timestamp
        }
        for i in interactions
    ])
    print(f"Loaded {len(interactions_df)} interactions")
    
    # Load places
    places = session.query(Place).all()
    places_df = pd.DataFrame([
        {
            'place_id': p.place_id,
            'category': p.category,
            'subcategory': p.category,
            'tags': p.tags,
            'city': p.city,
            # '': p.crowd_level.value if p.crowd_level else None,
            # 'avg_cost': p.avg_cost,
            'avg_rating': p.avg_rating,
            'description': p.description,
            'popularity_score': p.popularity_score
        }
        for p in places
    ])
    print(f"Loaded {len(places_df)} places")
    
    # Load users (for LambdaRank)
    users = session.query(User).all()
    users_df = pd.DataFrame([
        {
            'user_id': u.user_id,
            'age': u.age,
            # 'budget': u.budget,
            'companion_type': u.companion_type.value if u.companion_type else None,
            # 'preferred_crowd_level': u.preferred_crowd_level.value if u.preferred_crowd_level else None,
            'preferences': u.preferences
        }
        for u in users
    ])
    
    session.close()
    
    # Train models
    print("\nStarting training...")
    
    # 1. Train ALS
    cf_model = train_collaborative_filtering(interactions_df)
    
    # 2. Train Content-Based
    content_model = train_content_based(places_df)
    
    # 3. Train LambdaRank (keep existing)
    #ranker = train_lambdarank(interactions_df, users_df, places_df,settings)
    ranker = train_lambdarank(
    interactions_df.to_dict("records"),
    users_df.to_dict("records"),
    places_df.to_dict("records"),
    settings
)

    print("\n" + "="*50)
    print("Training Complete!")
    print("="*50)


if __name__ == "__main__":
    main()