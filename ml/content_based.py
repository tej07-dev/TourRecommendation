# ml/content_based_filtering.py
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Dict, Tuple, Optional
from config.settings import get_settings

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from utils.exception import TourismRecommenderException
import sys
class ContentBasedRecommender:
    """Content-based filtering using TF-IDF and cosine similarity"""
    
    def __init__(self):
        self.settings = get_settings()
        self.tfidf_vectorizer = None
        self.tfidf_matrix = None
        self.place_ids = None
        self.place_features = None
    
    def prepare_text_features(self, place_df: pd.DataFrame) -> pd.Series:
        """
        Combine place attributes into text for TF-IDF
        
        Args:
            place_df: DataFrame with place information
        
        Returns:
            Series of combined text features
        """
        def combine_features(row):
            features = []
            
            # Category (higher weight)
            if pd.notna(row.get('category')):
                features.extend([row['category']] * 3)
            
            # Subcategory
            if pd.notna(row.get('subcategory')):
                features.extend([row['subcategory']] * 2)
            
            # Tags
            if row.get('tags'):
                features.extend(row['tags'])
            
            # City
            if pd.notna(row.get('city')):
                features.append(row['city'])
            
            # Crowd level
            # if pd.notna(row.get('crowd_level')):
            #     features.append(f"crowd_{row['crowd_level']}")
            
            # # Cost bucket
            # if pd.notna(row.get('avg_cost')):
            #     cost_bucket = self._get_cost_bucket(row['avg_cost'])
            #     features.append(f"cost_{cost_bucket}")
            
            # Rating bucket
            if pd.notna(row.get('avg_rating')):
                rating_bucket = self._get_rating_bucket(row['avg_rating'])
                features.append(f"rating_{rating_bucket}")
            
            # Description keywords (first 100 words)
            if pd.notna(row.get('description')):
                desc_words = str(row['description']).lower().split()[:100]
                features.extend(desc_words)
            
            return ' '.join(features)
        
        return place_df.apply(combine_features, axis=1)
    
    def _get_cost_bucket(self, cost: float) -> str:
        """Bucket cost into categories"""
        if cost < 100:
            return 'very_cheap'
        elif cost < 500:
            return 'cheap'
        elif cost < 1500:
            return 'moderate'
        elif cost < 3000:
            return 'expensive'
        else:
            return 'very_expensive'
    
    def _get_rating_bucket(self, rating: float) -> str:
        """Bucket rating into categories"""
        if rating < 2.5:
            return 'poor'
        elif rating < 3.5:
            return 'below_avg'
        elif rating < 4.0:
            return 'avg'
        elif rating < 4.5:
            return 'good'
        else:
            return 'excellent'
    
    def fit(self, place_df: pd.DataFrame):
        """
        Fit TF-IDF model on place data
        
        Args:
            place_df: DataFrame with place information
        """
        logging.info(f"Fitting content-based model on {len(place_df)} places")
        
        # Prepare text features
        self.place_features = self.prepare_text_features(place_df)
        self.place_ids = place_df['place_id'].values
        
        # Fit TF-IDF
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=self.settings.TFIDF_MAX_FEATURES,
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.8,
            stop_words='english'
        )
        
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.place_features)
        
        logging.info(f"TF-IDF matrix shape: {self.tfidf_matrix.shape}")
    
    def get_similar_places(
        self,
        place_id: int,
        top_k: int = 20,
        exclude_ids: List[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Get places similar to a given place
        
        Args:
            place_id: Reference place ID
            top_k: Number of similar places to return
            exclude_ids: Place IDs to exclude from results
        
        Returns:
            List of (place_id, similarity_score) tuples
        """
        if self.tfidf_matrix is None:
            logging.error("Model not fitted. Call fit() first.")
            return []
        
        # Find index of place_id
        try:
            idx = np.where(self.place_ids == place_id)[0][0]
        except IndexError:
            logging.warning(f"Place {place_id} not found in training data")
            return []
        
        # Calculate cosine similarity
        place_vector = self.tfidf_matrix[idx]
        similarities = cosine_similarity(place_vector, self.tfidf_matrix).flatten()
        
        # Get top-k similar places
        similar_indices = similarities.argsort()[::-1]
        
        results = []
        exclude_set = set(exclude_ids) if exclude_ids else set()
        exclude_set.add(place_id)  # Exclude the query place itself
        
        for idx in similar_indices:
            pid = int(self.place_ids[idx])
            score = float(similarities[idx])
            
            if pid not in exclude_set and score >= self.settings.COSINE_SIMILARITY_THRESHOLD:
                results.append((pid, score))
                
                if len(results) >= top_k:
                    break
        
        return results

    def get_recommendations_for_user(
        self,
        user_id: int,
        interactions_df: pd.DataFrame,
        explicit_preferences: Dict,
        place_df: pd.DataFrame,
        top_k: int = 100,
        long_term_days: int = 180,
        short_term_limit: int = 10
    ) -> List[Tuple[int, float]]:
        """
        Context-aware content-based recommendations using contextual blending

        Components:
        - Long-term user taste (historical interactions)
        - Short-term intent (recent interactions)
        - Explicit preferences (current request)
        
        Args:
            user_id: User ID
            interactions_df: DataFrame with ALL user interactions
            explicit_preferences: Dict with user's explicit preferences
            place_df: DataFrame of available places
            top_k: Number of recommendations
            long_term_days: Days to consider for long-term profile
            short_term_limit: Number of recent interactions for short-term profile
        
        Returns:
            List of (place_id, score) tuples
        """
        try:
            if self.tfidf_matrix is None:
                logging.error("Model not fitted. Call fit() first.")
                return []

            # -------------------------------
            #  Filter user interactions
            # -------------------------------
            user_interactions = interactions_df[
                interactions_df["user_id"] == user_id
            ].copy()
            
            if user_interactions.empty:
                logging.warning(f"No interactions found for user {user_id}. Falling back to explicit preferences.")
                return self._recommend_from_explicit_preferences(
                    explicit_preferences,
                    place_df,
                    top_k
                )

            # ✅ FIX: ensure timestamp is datetime
            user_interactions["timestamp"] = pd.to_datetime(
                user_interactions["timestamp"],
                utc=True,
                errors="coerce"
            )

            now = pd.Timestamp.utcnow()

            # -------------------------------
            #  Long-term profile
            # -------------------------------
            long_term_cutoff = now - pd.Timedelta(days=long_term_days)
            long_term = user_interactions[
                user_interactions["timestamp"] >= long_term_cutoff
            ]

            long_term_vector = self._build_user_vector_from_interactions(long_term)

            # -------------------------------
            # Short-term profile
            # -------------------------------
            short_term = (
                user_interactions
                .sort_values("timestamp", ascending=False)
                .head(short_term_limit)
            )

            short_term_vector = self._build_user_vector_from_interactions(short_term)

            # -------------------------------
            # Explicit preference vector
            # -------------------------------
            explicit_vector = self._build_explicit_preference_vector(explicit_preferences)

            # -------------------------------
            # Contextual blending
            # -------------------------------
            vectors = []
            weights = []

            if long_term_vector is not None:
                vectors.append(long_term_vector)
                weights.append(0.5)

            if short_term_vector is not None:
                vectors.append(short_term_vector)
                weights.append(0.3)

            if explicit_vector is not None:
                vectors.append(explicit_vector)
                weights.append(0.2)

            if not vectors:
                logging.warning("No valid user context. Falling back to popular places.")
                return self._get_popular_places(place_df, top_k)

            from sklearn.preprocessing import normalize
            vectors=normalize(vectors)
            user_vector = np.average(vectors, axis=0, weights=weights)

            # -------------------------------
            #  Similarity scoring
            # -------------------------------
            similarities = cosine_similarity(
                user_vector.reshape(1, -1),
                self.tfidf_matrix
            ).flatten()

            top_indices = similarities.argsort()[::-1][:top_k]

            return [
                (int(self.place_ids[idx]), float(similarities[idx]))
                for idx in top_indices
                if similarities[idx] >= self.settings.COSINE_SIMILARITY_THRESHOLD
            ]
        except Exception as e:
            raise TourismRecommenderException(e,sys)
    
    def _build_user_vector_from_interactions(
        self,
        interactions_df: pd.DataFrame
    ) -> Optional[np.ndarray]:
        """
        Build user profile vector from interaction history
        
        Args:
            interactions_df: User's interactions
            
        Returns:
            Weighted average vector or None
        """
        if interactions_df.empty:
            return None

        vectors = []
        weights = []
        interaction_weights = {
            'save': 5.0,
            'route_requested': 4.0,
            'preview_viewed': 3.0,
            'click': 2.0,
            'search': 1.0,
            'skip': 0.0  # Negative signal, treat as 0
        }
        
        for _, row in interactions_df.iterrows():
            place_id = row.get("place_id")
            if pd.isna(place_id):
                continue
                
            idx = np.where(self.place_ids == place_id)[0]
            if len(idx) == 0:
                continue

            interaction_weight = interaction_weights.get(
                row.get("interaction_type", "click"), 1.0
            )

            vectors.append(self.tfidf_matrix[idx[0]].toarray()[0])
            weights.append(interaction_weight)

        if not vectors:
            return None

        return np.average(vectors, axis=0, weights=weights)
    
    def _build_explicit_preference_vector(
        self,
        explicit_preferences: Dict
    ) -> Optional[np.ndarray]:
        """
        Build user profile vector from explicit preferences
        
        Args:
            explicit_preferences: Dict with user preferences
            
        Returns:
            TF-IDF vector or None
        """
        text_parts = []

        if explicit_preferences.get("preferences"):
            text_parts.extend(explicit_preferences["preferences"] * 3)

        # if explicit_preferences.get("preferred_crowd_level"):
        #     text_parts.append(f"crowd_{explicit_preferences['preferred_crowd_level']}")

        if explicit_preferences.get("companion_type"):
            text_parts.append(explicit_preferences["companion_type"])

        # if explicit_preferences.get("budget"):
        #     cost_bucket = self._get_cost_bucket(explicit_preferences["budget"])
        #     text_parts.extend([f"cost_{cost_bucket}"] * 2)

        if not text_parts:
            return None

        user_text = " ".join(text_parts)
        return self.tfidf_vectorizer.transform([user_text]).toarray()[0]

    def _recommend_from_explicit_preferences(
        self,
        explicit_preferences: Dict,
        place_df: pd.DataFrame,
        top_k: int
    ) -> List[Tuple[int, float]]:
        """
        Fallback: recommend based only on explicit preferences
        """
        vector = self._build_explicit_preference_vector(explicit_preferences)
        if vector is None:
            return self._get_popular_places(place_df, top_k)

        similarities = cosine_similarity(
            vector.reshape(1, -1),
            self.tfidf_matrix
        ).flatten()

        top_indices = similarities.argsort()[::-1][:top_k]

        return [
            (int(self.place_ids[idx]), float(similarities[idx]))
            for idx in top_indices
            if similarities[idx] >= self.settings.COSINE_SIMILARITY_THRESHOLD
        ]
    
    def _get_popular_places(
        self,
        place_df: pd.DataFrame,
        top_k: int
    ) -> List[Tuple[int, float]]:
        """Fallback to popular places"""
        if 'popularity_score' not in place_df.columns:
            logging.warning("No popularity_score column, using random selection")
            sample_size = min(top_k, len(place_df))
            sample = place_df.sample(n=sample_size)
            return [
                (int(row['place_id']), 0.5)
                for _, row in sample.iterrows()
            ]
        
        sorted_places = place_df.nlargest(top_k, 'popularity_score')
        return [
            (int(row['place_id']), float(row.get('popularity_score', 0.5)))
            for _, row in sorted_places.iterrows()
        ]
    
    def get_batch_recommendations(
        self,
        user_profiles: List[Dict],
        interactions_df: pd.DataFrame,
        place_df: pd.DataFrame,
        top_k: int = 100
    ) -> Dict[int, List[Tuple[int, float]]]:
        """
        Get recommendations for multiple users at once
        
        Args:
            user_profiles: List of user preference dicts with 'user_id'
            interactions_df: All interactions
            place_df: DataFrame of places
            top_k: Number of recommendations per user
        
        Returns:
            Dict mapping user_id to list of (place_id, score)
        """
        results = {}
        
        for user_profile in user_profiles:
            user_id = user_profile.get('user_id')
            if user_id:
                recommendations = self.get_recommendations_for_user(
                    user_id=user_id,
                    interactions_df=interactions_df,
                    explicit_preferences=user_profile,
                    place_df=place_df,
                    top_k=top_k
                )
                results[user_id] = recommendations
        
        return results
    
    def save_model(self, filepath: str):
        """Save model to disk"""
        import joblib
        model_data = {
            'vectorizer': self.tfidf_vectorizer,
            'matrix': self.tfidf_matrix,
            'place_ids': self.place_ids,
            'place_features': self.place_features
        }
        joblib.dump(model_data, filepath)
        logging.info(f"Content-based model saved to {filepath}")
    
    def load_model(self, filepath: str):
        """Load model from disk"""
        import joblib
        model_data = joblib.load(filepath)
        self.tfidf_vectorizer = model_data['vectorizer']
        self.tfidf_matrix = model_data['matrix']
        self.place_ids = model_data['place_ids']
        self.place_features = model_data['place_features']
        logging.info(f"Content-based model loaded from {filepath}")
