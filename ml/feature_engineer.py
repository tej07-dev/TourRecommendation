# ml/feature_engineering.py
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from sklearn.preprocessing import StandardScaler, LabelEncoder
import logging

logger = logging.getLogger(__name__)

class FeatureEngineer:
    """Feature engineering for recommendation models"""
    
    def __init__(self):
        self.scalers = {}
        self.encoders = {}
    
    def prepare_user_features(self, user_data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare user features for model training
        
        Args:
            user_data: DataFrame with columns [user_id, age, gender, budget, 
                       preferred_crowd_level, preferences, companion_type]
        """
        df = user_data.copy()
        
        # Age buckets
        df['age_bucket'] = pd.cut(
            df['age'],
            bins=[0, 18, 25, 35, 45, 55, 100],
            labels=['<18', '18-25', '25-35', '35-45', '45-55', '55+']
        )
        
        # Budget buckets (normalize by log)
        df['budget_log'] = np.log1p(df['budget'])
        df['budget_bucket'] = pd.qcut(
            df['budget'],
            q=5,
            labels=['very_low', 'low', 'medium', 'high', 'very_high'],
            duplicates='drop'
        )
        
        # Encode categorical features
        categorical_cols = ['gender', 'preferred_crowd_level', 'companion_type']
        for col in categorical_cols:
            if col not in self.encoders:
                self.encoders[col] = LabelEncoder()
                df[f'{col}_encoded'] = self.encoders[col].fit_transform(df[col].fillna('unknown'))
            else:
                df[f'{col}_encoded'] = self.encoders[col].transform(df[col].fillna('unknown'))
        
        # One-hot encode preferences (multi-label)
        if 'preferences' in df.columns:
            all_categories = [
                'historical', 'nature', 'adventure', 'religious', 'beach',
                'museum', 'entertainment', 'shopping', 'food', 'nightlife',
                'cultural', 'wellness'
            ]
            for cat in all_categories:
                df[f'pref_{cat}'] = df['preferences'].apply(
                    lambda x: 1 if x and cat in x else 0
                )
        
        return df
    
    def prepare_place_features(self, place_data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare place features for model training
        
        Args:
            place_data: DataFrame with columns [place_id, name, category, city, 
                        latitude, longitude, avg_cost, avg_rating, crowd_level, 
                        tags, description, popularity_score]
        """
        df = place_data.copy()
        
        # Cost buckets
        df['cost_log'] = np.log1p(df['avg_cost'])
        df['cost_bucket'] = pd.qcut(
            df['avg_cost'],
            q=5,
            labels=['very_cheap', 'cheap', 'moderate', 'expensive', 'very_expensive'],
            duplicates='drop'
        )
        
        # Rating features
        df['rating_bucket'] = pd.cut(
            df['avg_rating'],
            bins=[0, 2.5, 3.5, 4.0, 4.5, 5.0],
            labels=['poor', 'below_avg', 'avg', 'good', 'excellent']
        )
        
        # Popularity percentile
        df['popularity_percentile'] = df['popularity_score'].rank(pct=True)
        
        # Encode categorical features
        if 'category' not in self.encoders:
            self.encoders['category'] = LabelEncoder()
            df['category_encoded'] = self.encoders['category'].fit_transform(df['category'])
        else:
            df['category_encoded'] = self.encoders['category'].transform(df['category'])
        
        if 'crowd_level' not in self.encoders:
            self.encoders['crowd_level'] = LabelEncoder()
            df['crowd_level_encoded'] = self.encoders['crowd_level'].fit_transform(
                df['crowd_level'].fillna('moderate')
            )
        else:
            df['crowd_level_encoded'] = self.encoders['crowd_level'].transform(
                df['crowd_level'].fillna('moderate')
            )
        
        # City popularity (number of places in city)
        city_counts = df['city'].value_counts()
        df['city_place_count'] = df['city'].map(city_counts)
        
        # Tag count
        df['tag_count'] = df['tags'].apply(lambda x: len(x) if x else 0)
        
        return df
    
    def prepare_interaction_features(
        self,
        interaction_data: pd.DataFrame,
        user_data: pd.DataFrame,
        place_data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Prepare features from user-place interactions
        
        Args:
            interaction_data: DataFrame with [user_id, place_id, interaction_type, timestamp]
            user_data: User features
            place_data: Place features
        """
        df = interaction_data.copy()
        
        # Time-based features
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['timestamp']).dt.dayofweek
        df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
        df['time_of_day'] = pd.cut(
            df['hour'],
            bins=[0, 6, 12, 18, 24],
            labels=['night', 'morning', 'afternoon', 'evening']
        )
        
        # Interaction type encoding
        interaction_weights = {
            'save': 5,
            'route_requested': 4,
            'preview_viewed': 3,
            'click': 2,
            'search': 1,
            'skip': -1
        }
        df['interaction_weight'] = df['interaction_type'].map(interaction_weights)
        
        # User engagement features
        user_stats = df.groupby('user_id').agg({
            'place_id': 'count',
            'interaction_weight': 'sum',
            'timestamp': lambda x: (datetime.utcnow() - pd.to_datetime(x).max()).days
        }).rename(columns={
            'place_id': 'user_interaction_count',
            'interaction_weight': 'user_engagement_score',
            'timestamp': 'days_since_last_interaction'
        })
        df = df.merge(user_stats, left_on='user_id', right_index=True, how='left')
        
        # Place popularity features
        place_stats = df[df['interaction_weight'] > 0].groupby('place_id').agg({
            'user_id': 'nunique',
            'interaction_weight': 'sum'
        }).rename(columns={
            'user_id': 'place_unique_users',
            'interaction_weight': 'place_total_engagement'
        })
        df = df.merge(place_stats, left_on='place_id', right_index=True, how='left')
        
        # Recency score (exponential decay)
        days_ago = (datetime.utcnow() - pd.to_datetime(df['timestamp'])).dt.days
        df['recency_score'] = np.exp(-days_ago / 30)  # 30-day half-life
        
        return df
    
    def create_user_place_features(
        self,
        user_df: pd.DataFrame,
        place_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Create cross features between users and places
        """
        # Merge user and place features
        user_df['key'] = 1
        place_df['key'] = 1
        merged = user_df.merge(place_df, on='key').drop('key', axis=1)
        
        # Budget compatibility
        merged['budget_match'] = (
            (merged['budget'] >= merged['avg_cost'] * 0.5) &
            (merged['budget'] <= merged['avg_cost'] * 2)
        ).astype(int)
        
        # Crowd level compatibility
        merged['crowd_match'] = (
            merged['preferred_crowd_level'] == merged['crowd_level']
        ).astype(int)
        
        # Preference match
        merged['preference_match'] = merged.apply(
            lambda row: 1 if row['category'] in (row['preferences'] or []) else 0,
            axis=1
        )
        
        # Distance calculation (if user has home location)
        from geopy.distance import geodesic
        merged['distance_km'] = merged.apply(
            lambda row: geodesic(
                (row['home_latitude'], row['home_longitude']),
                (row['latitude'], row['longitude'])
            ).km if pd.notna(row['home_latitude']) else np.nan,
            axis=1
        )
        
        # Distance buckets
        merged['distance_bucket'] = pd.cut(
            merged['distance_km'],
            bins=[0, 10, 25, 50, 100, 500],
            labels=['very_close', 'close', 'moderate', 'far', 'very_far']
        )
        
        return merged
    def create_ranking_features(
        self,
        candidates: pd.DataFrame,
        user_id: int,
        interaction_history: pd.DataFrame
    ) -> pd.DataFrame:
        df = candidates.copy()

        if not interaction_history.empty:
            user_interactions = interaction_history[
                interaction_history["user_id"] == user_id
            ]

            interacted_categories = user_interactions.merge(
                df[["place_id", "category"]],
                on="place_id",
                how="inner"
            )["category"].value_counts()

            df["category_familiarity"] = df["category"].map(interacted_categories).fillna(0)

            skipped_places = set(
                user_interactions[user_interactions["interaction_type"] == "skip"]["place_id"]
            )
            df["was_skipped"] = df["place_id"].isin(skipped_places).astype(int)

        else:
            df["category_familiarity"] = 0
            df["was_skipped"] = 0

        # ❌ DO NOT add candidate position
        return df

    # def create_ranking_features(
    #     self,
    #     candidates: pd.DataFrame,
    #     user_id: int,
    #     interaction_history: pd.DataFrame
    # ) -> pd.DataFrame:
    #     """
    #     Create features for ranking model
        
    #     Args:
    #         candidates: DataFrame of candidate places with scores
    #         user_id: Current user
    #         interaction_history: User's interaction history
    #     """
    #     df = candidates.copy()
        
    #     # Historical interaction with similar places
    #     if not interaction_history.empty:
    #         user_interactions = interaction_history[
    #             interaction_history['user_id'] == user_id
    #         ]
            
    #         # Places from same category
    #         interacted_categories = user_interactions.merge(
    #             df[['place_id', 'category']],
    #             on='place_id',
    #             how='inner'
    #         )['category'].value_counts().to_dict()
            
    #         df['category_familiarity'] = df['category'].map(interacted_categories).fillna(0)
            
    #         # Previously skipped places
    #         skipped_places = set(
    #             user_interactions[
    #                 user_interactions['interaction_type'] == 'skip'
    #             ]['place_id']
    #         )
    #         df['was_skipped'] = df['place_id'].isin(skipped_places).astype(int)
    #     else:
    #         df['category_familiarity'] = 0
    #         df['was_skipped'] = 0
        
    #     # Position in candidate list (for learning-to-rank)
    #     df['candidate_position'] = range(len(df))
    #     df['candidate_position_normalized'] = df['candidate_position'] / len(df)
        
    #     return df
    
    def normalize_features(
        self,
        df: pd.DataFrame,
        numeric_columns: List[str],
        fit: bool = True
    ) -> pd.DataFrame:
        """Normalize numeric features"""
        df = df.copy()
        
        for col in numeric_columns:
            if col in df.columns:
                if fit:
                    if col not in self.scalers:
                        self.scalers[col] = StandardScaler()
                    df[f'{col}_scaled'] = self.scalers[col].fit_transform(
                        df[[col]].fillna(0)
                    )
                else:
                    if col in self.scalers:
                        df[f'{col}_scaled'] = self.scalers[col].transform(
                            df[[col]].fillna(0)
                        )
        
        return df