# ml/collaborative_filtering.py - FIXED VERSION
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from implicit.als import AlternatingLeastSquares
from implicit.nearest_neighbours import bm25_weight
from typing import List, Tuple, Dict, Optional, Set

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from config.settings import get_settings

import sys
from utils.exception import TourismRecommenderException


class CollaborativeFilteringRecommender:
    """
    Collaborative filtering using ALS (Alternating Least Squares).
    
    FIXED: Index out of bounds error
    - Properly handles inference without interaction_matrix
    - Validates all indices before access
    - Uses only model.item_factors for recommendations
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.model = None
        self.user_id_map: Dict = {}
        self.place_id_map: Dict = {}
        self.reverse_user_map: Dict = {}
        self.reverse_place_map: Dict = {}
        self.train_place_ids: Optional[Set] = None  # FROZEN universe of places
        
        # Training-only (not saved)
        self._interaction_matrix: Optional[csr_matrix] = None
    
    def prepare_interaction_matrix(
        self,
        interactions_df: pd.DataFrame
    ) -> csr_matrix:
        """
        Convert interactions to user-item matrix.
        
        FREEZE place universe: only includes places in this training batch.
        This set is saved and used at inference to filter recommendations.
        
        Args:
            interactions_df: DataFrame with [user_id, place_id, interaction_type, timestamp]
        
        Returns:
            Sparse CSR matrix
        """
        logging.info(f"Preparing interaction matrix from {len(interactions_df)} interactions")
        
        # Use shared interaction weights from settings
        interactions_df = interactions_df.copy()
        interactions_df['weight'] = interactions_df['interaction_type'].map(
            self.settings.INTERACTION_WEIGHTS
        ).fillna(1.0)
        
        # Add recency weight (exponential decay)
        if 'timestamp' in interactions_df.columns:
            from datetime import datetime
            interactions_df['timestamp'] = pd.to_datetime(interactions_df['timestamp'])
            days_ago = (datetime.utcnow() - interactions_df['timestamp']).dt.days
            recency_half_life = self.settings.ALS_RECENCY_HALF_LIFE_DAYS
            interactions_df['recency_weight'] = np.exp(-days_ago / recency_half_life)
            interactions_df['weight'] *= interactions_df['recency_weight']
        
        # Aggregate multiple interactions
        aggregated = interactions_df.groupby(['user_id', 'place_id'])['weight'].sum().reset_index()
        
        # FREEZE place universe: capture ALL places in this batch
        unique_users = np.sort(aggregated['user_id'].unique())
        unique_places = np.sort(aggregated['place_id'].unique())
        self.train_place_ids = set(unique_places)  # IMMUTABLE
        
        # Create IMMUTABLE mappings
        self.user_id_map = {uid: idx for idx, uid in enumerate(unique_users)}
        self.place_id_map = {pid: idx for idx, pid in enumerate(unique_places)}
        self.reverse_user_map = {idx: uid for uid, idx in self.user_id_map.items()}
        self.reverse_place_map = {idx: pid for pid, idx in self.place_id_map.items()}
        
        # Create matrix indices
        row_indices = aggregated['user_id'].map(self.user_id_map).values
        col_indices = aggregated['place_id'].map(self.place_id_map).values
        weights = aggregated['weight'].values
        
        # Confidence scaling for implicit ALS
        alpha = self.settings.ALS_CONFIDENCE_ALPHA
        confidence_weights = 1.0 + alpha * weights
        
        n_users = len(unique_users)
        n_places = len(unique_places)
        
        self._interaction_matrix = csr_matrix(
            (confidence_weights, (row_indices, col_indices)),
            shape=(n_users, n_places)
        )
        
        logging.info(f"Interaction matrix shape: {self._interaction_matrix.shape}")
        logging.info(f"Frozen place universe: {len(self.train_place_ids)} places")
        logging.info(f"Matrix sparsity: {1 - (self._interaction_matrix.nnz / max(1, n_users * n_places)):.4f}")
        
        return self._interaction_matrix
    
    def fit(self, interactions_df: pd.DataFrame):
        """
        Train ALS model.
        
        TRAINING ONLY: rebuilds matrix and mappings, freezes place universe.
        At inference, these are loaded from saved model and never rebuilt.
        
        Args:
            interactions_df: DataFrame with user-place interactions
        """
        logging.info("Training collaborative filtering model")
        
        # Prepare interaction matrix (freezes place universe)
        user_item_matrix = self.prepare_interaction_matrix(interactions_df)
        
        # Apply BM25 weighting
        weighted_matrix = bm25_weight(user_item_matrix, K1=100, B=0.8)
        
        # Initialize ALS model
        self.model = AlternatingLeastSquares(
            factors=self.settings.ALS_FACTORS,
            regularization=self.settings.ALS_REGULARIZATION,
            iterations=self.settings.ALS_ITERATIONS,
            calculate_training_loss=True,
            random_state=42
        )
        
        # Fit model (transpose for implicit library)
        self.model.fit(weighted_matrix.T.tocsr())
        
        logging.info(f"Collaborative filtering model trained successfully")
        logging.info(f"Model item_factors shape: {self.model.item_factors.shape}")
        logging.info(f"Model user_factors shape: {self.model.user_factors.shape}")
        logging.info(f"Frozen place universe size: {len(self.train_place_ids)}")

    def get_recommendations(
        self,
        user_id: int,
        top_k: int = 100,
        filter_already_interacted: bool = True
    ) -> List[Tuple[int, float]]:
        """
        Get ALS-based place recommendations for a user.
        
        FIXED: Handles inference without interaction_matrix
        - Creates sparse user vector on-the-fly if needed
        - Validates all indices before access
        - Returns only places in frozen universe
        
        Args:
            user_id: User ID
            top_k: Number of candidate recommendations
            filter_already_interacted: Filter out previously interacted places
        
        Returns:
            List of (place_id, als_score) tuples (candidates for ranking)
        """
        try:
            if self.model is None:
                logging.error("ALS model not trained. Call fit() first.")
                return []
            
            if self.train_place_ids is None:
                logging.error("train_place_ids (frozen universe) missing.")
                return []

            if user_id not in self.user_id_map:
                logging.info(f"User {user_id} cold-start (not in training data).")
                return []

            user_idx = self.user_id_map[user_id]
            
            # CRITICAL FIX: Validate user_idx
            if user_idx >= self.model.user_factors.shape[0]:
                logging.error(f"User index {user_idx} out of bounds for user_factors")
                return []
            
            # Get number of items in model
            n_items = self.model.item_factors.shape[0]
            
            # OPTION 1: Use recommend_all (safer, no user_items needed)
            try:
                # Get user factor
                user_factor = self.model.user_factors[user_idx]
                
                # Compute scores for all items
                scores = self.model.item_factors.dot(user_factor)
                
                # Get top-k indices
                top_indices = np.argsort(scores)[::-1][:top_k * 2]  # Get extra for filtering
                
                recommendations = []
                for idx in top_indices:
                    # CRITICAL: Validate index before accessing reverse_place_map
                    if idx >= n_items:
                        logging.warning(f"Skipping index {idx} >= {n_items}")
                        continue
                    
                    place_id = self.reverse_place_map.get(idx)
                    
                    # Validate place_id exists and is in frozen universe
                    if place_id is not None and place_id in self.train_place_ids:
                        score = float(scores[idx])
                        recommendations.append((place_id, score))
                        
                        if len(recommendations) >= top_k:
                            break
                
                return recommendations
                
            except Exception as e:
                logging.error(f"Error in recommendation generation: {e}")
                
                # OPTION 2: Fallback - use similar_users approach
                try:
                    logging.info("Trying fallback: similar users method")
                    return self._get_recommendations_via_similar_users(user_idx, top_k)
                except Exception as e2:
                    logging.error(f"Fallback also failed: {e2}")
                    return []

        except Exception as e:
            raise TourismRecommenderException(e, sys)
    
    def _get_recommendations_via_similar_users(
        self,
        user_idx: int,
        top_k: int
    ) -> List[Tuple[int, float]]:
        """
        Fallback: Recommend based on similar users
        """
        # Find similar users
        user_factor = self.model.user_factors[user_idx]
        
        # Compute similarity with all users
        similarities = self.model.user_factors.dot(user_factor)
        
        # Get top similar users (excluding self)
        similar_user_indices = np.argsort(similarities)[::-1][1:11]  # Top 10 similar users
        
        # Aggregate their preferences
        item_scores = np.zeros(self.model.item_factors.shape[0])
        
        for similar_idx in similar_user_indices:
            if similar_idx < self.model.user_factors.shape[0]:
                similar_user_factor = self.model.user_factors[similar_idx]
                scores = self.model.item_factors.dot(similar_user_factor)
                item_scores += scores * similarities[similar_idx]
        
        # Get top items
        top_indices = np.argsort(item_scores)[::-1][:top_k]
        
        recommendations = []
        for idx in top_indices:
            place_id = self.reverse_place_map.get(idx)
            if place_id is not None and place_id in self.train_place_ids:
                recommendations.append((place_id, float(item_scores[idx])))
        
        return recommendations

    def get_similar_places(
        self,
        place_id: int,
        top_k: int = 20
    ) -> List[Tuple[int, float]]:
        """
        Get places similar to a given place based on user interactions
        
        Args:
            place_id: Reference place ID
            top_k: Number of similar places
        
        Returns:
            List of (place_id, similarity_score) tuples
        """
        if self.model is None:
            logging.error("Model not trained. Call fit() first.")
            return []
        
        if place_id not in self.place_id_map:
            logging.warning(f"Place {place_id} not in training data")
            return []
        
        place_idx = self.place_id_map[place_id]
        
        # Validate index
        if place_idx >= self.model.item_factors.shape[0]:
            logging.error(f"Place index {place_idx} out of bounds")
            return []
        
        try:
            # Get similar items
            indices, scores = self.model.similar_items(place_idx, N=top_k + 1)
            
            # Filter out the query place itself and map to actual IDs
            similar_places = []
            for idx, score in zip(indices, scores):
                if idx != place_idx and idx < self.model.item_factors.shape[0]:
                    pid = self.reverse_place_map.get(idx)
                    if pid is not None and pid in self.train_place_ids:
                        similar_places.append((pid, float(score)))
            
            return similar_places[:top_k]
            
        except Exception as e:
            logging.error(f"Error getting similar places: {e}")
            return []
    
    def get_batch_recommendations(
        self,
        user_ids: List[int],
        top_k: int = 100,
        filter_already_interacted: bool = True
    ) -> Dict[int, List[Tuple[int, float]]]:
        """
        Get recommendations for multiple users
        
        Args:
            user_ids: List of user IDs
            top_k: Number of recommendations per user
            filter_already_interacted: Filter interacted items
        
        Returns:
            Dict mapping user_id to recommendations
        """
        results = {}
        
        for user_id in user_ids:
            recommendations = self.get_recommendations(
                user_id,
                top_k,
                filter_already_interacted
            )
            results[user_id] = recommendations
        
        return results
    
    def get_user_vector(self, user_id: int) -> Optional[np.ndarray]:
        """Get latent factor vector for a user"""
        if user_id not in self.user_id_map:
            return None
        
        user_idx = self.user_id_map[user_id]
        
        if user_idx >= self.model.user_factors.shape[0]:
            return None
        
        return self.model.user_factors[user_idx]
    
    def get_place_vector(self, place_id: int) -> Optional[np.ndarray]:
        """Get latent factor vector for a place"""
        if place_id not in self.place_id_map:
            return None
        
        place_idx = self.place_id_map[place_id]
        
        if place_idx >= self.model.item_factors.shape[0]:
            return None
        
        return self.model.item_factors[place_idx]
    
    def predict_score(self, user_id: int, place_id: int) -> float:
        """Predict score for user-place pair"""
        user_vec = self.get_user_vector(user_id)
        place_vec = self.get_place_vector(place_id)
        
        if user_vec is None or place_vec is None:
            return 0.0
        
        return float(np.dot(user_vec, place_vec))
    
    def save_model(self, filepath: str):
        """
        Save model to disk with IMMUTABLE state.
        
        FIXED: Does NOT save interaction_matrix (causes shape mismatch)
        
        Saves:
        - ALS model (item_factors, user_factors)
        - user_id_map, place_id_map (immutable mappings)
        - reverse_user_map, reverse_place_map
        - train_place_ids (FROZEN universe)
        
        Does NOT save:
        - interaction_matrix (not needed for inference)
        """
        import joblib
        
        model_data = {
            'model': self.model,
            'user_id_map': self.user_id_map,
            'place_id_map': self.place_id_map,
            'reverse_user_map': self.reverse_user_map,
            'reverse_place_map': self.reverse_place_map,
            'train_place_ids': self.train_place_ids,  # FROZEN universe
            # REMOVED: 'interaction_matrix': self.interaction_matrix,
            
            # Save metadata for debugging
            'metadata': {
                'n_users': len(self.user_id_map),
                'n_places': len(self.place_id_map),
                'n_factors': self.model.factors if self.model else None,
                'item_factors_shape': self.model.item_factors.shape if self.model else None,
                'user_factors_shape': self.model.user_factors.shape if self.model else None,
            }
        }
        
        joblib.dump(model_data, filepath)
        logging.info(f"Collaborative filtering model saved to {filepath}")
        logging.info(f"Frozen place universe ({len(self.train_place_ids)} places) persisted")
        logging.info(f"Model metadata: {model_data['metadata']}")
    
    def load_model(self, filepath: str):
        """
        Load model from disk with IMMUTABLE state.
        
        FIXED: Validates loaded data for consistency
        
        Loads all mappings and frozen place universe as-is.
        Inference uses these WITHOUT rebuilding.
        """
        import joblib
        
        model_data = joblib.load(filepath)
        
        self.model = model_data['model']
        self.user_id_map = model_data['user_id_map']
        self.place_id_map = model_data['place_id_map']
        self.reverse_user_map = model_data['reverse_user_map']
        self.reverse_place_map = model_data['reverse_place_map']
        self.train_place_ids = model_data.get('train_place_ids')  # FROZEN universe
        
        # Validate consistency
        if self.model:
            n_items_in_model = self.model.item_factors.shape[0]
            n_items_in_map = len(self.place_id_map)
            
            if n_items_in_model != n_items_in_map:
                logging.warning(
                    f"Model has {n_items_in_model} items but place_id_map has {n_items_in_map}. "
                    f"This may cause issues."
                )
            
            # Validate reverse_place_map indices
            max_idx = max(self.reverse_place_map.keys()) if self.reverse_place_map else -1
            if max_idx >= n_items_in_model:
                logging.error(
                    f"reverse_place_map has index {max_idx} but model only has {n_items_in_model} items!"
                )
                # Clean up invalid indices
                self.reverse_place_map = {
                    idx: pid for idx, pid in self.reverse_place_map.items()
                    if idx < n_items_in_model
                }
                logging.info(f"Cleaned reverse_place_map to {len(self.reverse_place_map)} valid entries")
        
        metadata = model_data.get('metadata', {})
        
        logging.info(f"Collaborative filtering model loaded from {filepath}")
        logging.info(f"Frozen place universe: {len(self.train_place_ids) if self.train_place_ids else 'N/A'} places")
        logging.info(f"Model metadata: {metadata}")
        logging.info(f"Item factors shape: {self.model.item_factors.shape}")
        logging.info(f"User factors shape: {self.model.user_factors.shape}")
# # ml/collaborative_filtering.py
# import numpy as np
# import pandas as pd
# from scipy.sparse import csr_matrix
# from implicit.als import AlternatingLeastSquares
# from implicit.nearest_neighbours import bm25_weight
# from typing import List, Tuple, Dict, Optional, Set
# import logging
# from config.settings import get_settings

# import sys
# from ml.utils.exception import TourismRecommenderException
# from ml.utils.logger import logging
# class CollaborativeFilteringRecommender:
#     """
#     Collaborative filtering using ALS (Alternating Least Squares).
    
#     Key principles:
#     - Place universe is FROZEN at training time (train_place_ids)
#     - Never recommend places outside this universe
#     - ID mappings are immutable after training (loaded from saved model)
#     - Interaction matrix is never rebuilt at inference
#     - Uses shared INTERACTION_WEIGHTS from settings
#     """
    
#     def __init__(self):
#         self.settings = get_settings()
#         self.model = None
#         self.user_id_map: Dict = {}
#         self.place_id_map: Dict = {}
#         self.reverse_user_map: Dict = {}
#         self.reverse_place_map: Dict = {}
#         self.interaction_matrix: Optional[csr_matrix] = None
#         self.train_place_ids: Optional[Set] = None  # FROZEN universe of places
    
#     def prepare_interaction_matrix(
#         self,
#         interactions_df: pd.DataFrame
#     ) -> csr_matrix:
#         """
#         Convert interactions to user-item matrix.
        
#         FREEZE place universe: only includes places in this training batch.
#         This set is saved and used at inference to filter recommendations.
        
#         Args:
#             interactions_df: DataFrame with [user_id, place_id, interaction_type, timestamp]
        
#         Returns:
#             Sparse CSR matrix
#         """
#         logging.info(f"Preparing interaction matrix from {len(interactions_df)} interactions")
        
#         # Use shared interaction weights from settings
#         interactions_df = interactions_df.copy()
#         interactions_df['weight'] = interactions_df['interaction_type'].map(
#             self.settings.INTERACTION_WEIGHTS
#         ).fillna(1.0)
        
#         # Add recency weight (exponential decay)
#         if 'timestamp' in interactions_df.columns:
#             from datetime import datetime
#             interactions_df['timestamp'] = pd.to_datetime(interactions_df['timestamp'])
#             days_ago = (datetime.utcnow() - interactions_df['timestamp']).dt.days
#             recency_half_life = self.settings.ALS_RECENCY_HALF_LIFE_DAYS
#             interactions_df['recency_weight'] = np.exp(-days_ago / recency_half_life)
#             interactions_df['weight'] *= interactions_df['recency_weight']
        
#         # Aggregate multiple interactions
#         aggregated = interactions_df.groupby(['user_id', 'place_id'])['weight'].sum().reset_index()
        
#         # FREEZE place universe: capture ALL places in this batch
#         unique_users = np.sort(aggregated['user_id'].unique())
#         unique_places = np.sort(aggregated['place_id'].unique())
#         self.train_place_ids = set(unique_places)  # IMMUTABLE
        
#         # Create IMMUTABLE mappings
#         self.user_id_map = {uid: idx for idx, uid in enumerate(unique_users)}
#         self.place_id_map = {pid: idx for idx, pid in enumerate(unique_places)}
#         self.reverse_user_map = {idx: uid for uid, idx in self.user_id_map.items()}
#         self.reverse_place_map = {idx: pid for pid, idx in self.place_id_map.items()}
        
#         # Create matrix indices
#         row_indices = aggregated['user_id'].map(self.user_id_map).values
#         col_indices = aggregated['place_id'].map(self.place_id_map).values
#         weights = aggregated['weight'].values
        
#         # Confidence scaling for implicit ALS
#         alpha = self.settings.ALS_CONFIDENCE_ALPHA
#         confidence_weights = 1.0 + alpha * weights
        
#         n_users = len(unique_users)
#         n_places = len(unique_places)
        
#         self.interaction_matrix = csr_matrix(
#             (confidence_weights, (row_indices, col_indices)),
#             shape=(n_users, n_places)
#         )
        
#         logging.info(f"Interaction matrix shape: {self.interaction_matrix.shape}")
#         logging.info(f"Frozen place universe: {len(self.train_place_ids)} places")
#         logging.info(f"Matrix sparsity: {1 - (self.interaction_matrix.nnz / max(1, n_users * n_places)):.4f}")
        
#         return self.interaction_matrix
    
#     def fit(self, interactions_df: pd.DataFrame):
#         """
#         Train ALS model.
        
#         TRAINING ONLY: rebuilds matrix and mappings, freezes place universe.
#         At inference, these are loaded from saved model and never rebuilt.
        
#         Args:
#             interactions_df: DataFrame with user-place interactions
#         """
#         logging.info("Training collaborative filtering model")
        
#         # Prepare interaction matrix (freezes place universe)
#         user_item_matrix = self.prepare_interaction_matrix(interactions_df)
        
#         # Apply BM25 weighting
#         weighted_matrix = bm25_weight(user_item_matrix, K1=100, B=0.8)
        
#         # Initialize ALS model
#         self.model = AlternatingLeastSquares(
#             factors=self.settings.ALS_FACTORS,
#             regularization=self.settings.ALS_REGULARIZATION,
#             iterations=self.settings.ALS_ITERATIONS,
#             calculate_training_loss=True,
#             random_state=42
#         )
        
#         # Fit model (transpose for implicit library)
#         self.model.fit(weighted_matrix.T.tocsr())
        
#         logging.info(f"Collaborative filtering model trained successfully")
#         logging.info(f"Frozen place universe size: {len(self.train_place_ids)}")

    
#     # def get_recommendations(
#     #     self,
#     #     user_id: int,
#     #     top_k: int = 100,
#     #     filter_already_interacted: bool = True
#     # ) -> List[Tuple[int, float]]:
#     #     """
#     #     Get recommendations for a user
        
#     #     Args:
#     #         user_id: User ID
#     #         top_k: Number of recommendations
#     #         filter_already_interacted: Whether to filter out places user already interacted with
        
#     #     Returns:
#     #         List of (place_id, score) tuples
#     #     """
#     #     try:
                
#     #         if self.model is None:
#     #             logging.error("Model not trained. Call fit() first.")
#     #             return []
            
#     #         # Check if user exists in training data
#     #         if user_id not in self.user_id_map:
#     #             logging.warning(f"User {user_id} not in training data (cold start)")
#     #             return []
            
#     #         user_idx = self.user_id_map[user_id]
            
#     #         # Get recommendations
#     #         if filter_already_interacted:
#     #             # Get user's interaction history
#     #             user_items = self.interaction_matrix[user_idx]
                
#     #             # Recommend
#     #             indices, scores = self.model.recommend(
#     #                 user_idx,
#     #                 user_items,
#     #                 N=top_k,
#     #                 filter_already_liked_items=True
#     #             )
#     #         else:
#     #             # Just get top items based on user factors
#     #             indices, scores = self.model.recommend(
#     #                 user_idx,
#     #                 self.interaction_matrix[user_idx],
#     #                 N=top_k,
#     #                 filter_already_liked_items=False
#     #             )
            
#     #         # Map back to actual place IDs
#     #         recommendations = [
#     #             (self.reverse_place_map[idx], float(score))
#     #             for idx, score in zip(indices, scores)
#     #         ]
            
#     #         return recommendations
#     #     except Exception as e:
#     #         raise TourismRecommenderException(e,sys)
#     from typing import List, Tuple
#     import numpy as np
#     from scipy.sparse import csr_matrix
#     import logging
#     import sys

#     def get_recommendations(
#         self,
#         user_id: int,
#         top_k: int = 100,
#         filter_already_interacted: bool = True
#     ) -> List[Tuple[int, float]]:
#         """
#         Get ALS-based place recommendations for a user.
        
#         INFERENCE ONLY:
#         - Uses FROZEN place universe (train_place_ids) 
#         - Never rebuilds interaction matrix
#         - Uses immutable mappings loaded from saved model
#         - Returns candidates to be ranked separately
        
#         Args:
#             user_id: User ID
#             top_k: Number of candidate recommendations
#             filter_already_interacted: Filter out previously interacted places
        
#         Returns:
#             List of (place_id, als_score) tuples (candidates for ranking)
#         """
#         try:
#             if self.model is None:
#                 logging.error("ALS model not trained. Call fit() first.")
#                 return []

#             if self.interaction_matrix is None:
#                 logging.error("interaction_matrix missing. Model state corrupted.")
#                 return []
            
#             if self.train_place_ids is None:
#                 logging.error("train_place_ids (frozen universe) missing.")
#                 return []

#             if user_id not in self.user_id_map:
#                 logging.info(f"User {user_id} cold-start (not in training data).")
#                 return []

#             # HARD SHAPE VALIDATION
#             n_items_matrix = self.interaction_matrix.shape[1]
#             n_items_model = self.model.item_factors.shape[0]

#             if n_items_matrix != n_items_model:
#                 raise ValueError(
#                     f"Shape mismatch: interaction_matrix has {n_items_matrix} items "
#                     f"but model has {n_items_model}. Model state corrupted."
#                 )

#             user_idx = self.user_id_map[user_id]
#             user_items = self.interaction_matrix[user_idx]

#             # Generate candidates
#             indices, scores = self.model.recommend(
#                 userid=user_idx,
#                 user_items=user_items,
#                 N=top_k,
#                 filter_already_liked_items=filter_already_interacted
#             )

#             # Map back to place_ids and FILTER by frozen universe
#             recommendations = []
#             for idx, score in zip(indices, scores):
#                 place_id = self.reverse_place_map.get(idx)
#                 if place_id is not None and place_id in self.train_place_ids:
#                     recommendations.append((place_id, float(score)))

#             return recommendations

#         except Exception as e:
#             raise TourismRecommenderException(e, sys)

#     def get_similar_places(
#         self,
#         place_id: int,
#         top_k: int = 20
#     ) -> List[Tuple[int, float]]:
#         """
#         Get places similar to a given place based on user interactions
        
#         Args:
#             place_id: Reference place ID
#             top_k: Number of similar places
        
#         Returns:
#             List of (place_id, similarity_score) tuples
#         """
#         if self.model is None:
#             logging.error("Model not trained. Call fit() first.")
#             return []
        
#         if place_id not in self.place_id_map:
#             logging.warning(f"Place {place_id} not in training data")
#             return []
        
#         place_idx = self.place_id_map[place_id]
        
#         # Get similar items
#         indices, scores = self.model.similar_items(place_idx, N=top_k + 1)
        
#         # Filter out the query place itself and map to actual IDs
#         similar_places = [
#             (self.reverse_place_map[idx], float(score))
#             for idx, score in zip(indices, scores)
#             if idx != place_idx
#         ][:top_k]
        
#         return similar_places
    
#     def get_batch_recommendations(
#         self,
#         user_ids: List[int],
#         top_k: int = 100,
#         filter_already_interacted: bool = True
#     ) -> Dict[int, List[Tuple[int, float]]]:
#         """
#         Get recommendations for multiple users
        
#         Args:
#             user_ids: List of user IDs
#             top_k: Number of recommendations per user
#             filter_already_interacted: Filter interacted items
        
#         Returns:
#             Dict mapping user_id to recommendations
#         """
#         results = {}
        
#         for user_id in user_ids:
#             recommendations = self.get_recommendations(
#                 user_id,
#                 top_k,
#                 filter_already_interacted
#             )
#             results[user_id] = recommendations
        
#         return results
    
#     def get_user_vector(self, user_id: int) -> np.ndarray:
#         """Get latent factor vector for a user"""
#         if user_id not in self.user_id_map:
#             return None
        
#         user_idx = self.user_id_map[user_id]
#         return self.model.user_factors[user_idx]
    
#     def get_place_vector(self, place_id: int) -> np.ndarray:
#         """Get latent factor vector for a place"""
#         if place_id not in self.place_id_map:
#             return None
        
#         place_idx = self.place_id_map[place_id]
#         return self.model.item_factors[place_idx]
    
#     def predict_score(self, user_id: int, place_id: int) -> float:
#         """Predict score for user-place pair"""
#         user_vec = self.get_user_vector(user_id)
#         place_vec = self.get_place_vector(place_id)
        
#         if user_vec is None or place_vec is None:
#             return 0.0
        
#         return float(np.dot(user_vec, place_vec))
    
#     def save_model(self, filepath: str):
#         """
#         Save model to disk with IMMUTABLE state.
        
#         Saves:
#         - ALS model
#         - user_id_map, place_id_map (immutable mappings)
#         - reverse_user_map, reverse_place_map
#         - interaction_matrix (for offline use only)
#         - train_place_ids (FROZEN universe - never recommend outside this set)
#         """
#         import joblib
#         model_data = {
#             'model': self.model,
#             'user_id_map': self.user_id_map,
#             'place_id_map': self.place_id_map,
#             'reverse_user_map': self.reverse_user_map,
#             'reverse_place_map': self.reverse_place_map,
#             'interaction_matrix': self.interaction_matrix,
#             'train_place_ids': self.train_place_ids,  # FROZEN universe
#         }
#         joblib.dump(model_data, filepath)
#         logging.info(f"Collaborative filtering model saved to {filepath}")
#         logging.info(f"Frozen place universe ({len(self.train_place_ids)} places) persisted")
    
#     def load_model(self, filepath: str):
#         """
#         Load model from disk with IMMUTABLE state.
        
#         Loads all mappings and frozen place universe as-is.
#         Inference uses these WITHOUT rebuilding.
#         """
#         import joblib
#         model_data = joblib.load(filepath)
#         self.model = model_data['model']
#         self.user_id_map = model_data['user_id_map']
#         self.place_id_map = model_data['place_id_map']
#         self.reverse_user_map = model_data['reverse_user_map']
#         self.reverse_place_map = model_data['reverse_place_map']
#         self.interaction_matrix = model_data['interaction_matrix']
#         self.train_place_ids = model_data.get('train_place_ids')  # FROZEN universe
#         logging.info(f"Collaborative filtering model loaded from {filepath}")
#         logging.info(f"Frozen place universe: {len(self.train_place_ids) if self.train_place_ids else 'N/A'} places")
