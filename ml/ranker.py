import numpy as np
import lightgbm as lgb

from typing import List, Dict, Tuple, Optional, Union
import pickle
from pathlib import Path
from datetime import datetime

class LambdaRankModel:
    """
    Advanced LambdaRank implementation using LightGBM.
    Combines custom travel-domain feature engineering with a 
    listwise NDCG optimization objective.
    """
    
    def __init__(
        self,
        learning_rate: float = 0.05,
        n_estimators: int = 300,
        num_leaves: int = 31,
        random_state: int = 42
    ):
        self.model = lgb.LGBMRanker(
            objective="lambdarank",
            metric="ndcg",
            boosting_type="gbdt",
            learning_rate=learning_rate,
            n_estimators=n_estimators,
            num_leaves=num_leaves,
            random_state=random_state,
            importance_type="gain",
            label_gain=[0, 1, 3, 7, 15, 31], # Custom gain for relevance levels
        )
        
        self.feature_names = [
            'norm_age', #'budget_val', 
            'companion_val', 'rating_val', 
            'popularity_val', #'budget_match', 'crowd_match', 
            'ncf_score', 'content_score', 'hybrid_avg', 
            'cat_match', 'tag_match', 'dist_score', 
            'time_val', 'weather_score'
        ]
        self.is_fitted = False

    def calculate_relevance_from_interactions(self, interaction_type: str, rating: Optional[float] = None) -> int:
        """
        Utility to map interaction types to integer relevance levels for LambdaRank.
        Higher is better.
        """
        relevance_map = {
            'preview_viewed': 1,
            'click': 2,
           # 'like': 3,
            'save': 4,
            'route_requested':3

            #'book': 5
        }
        base_rel = relevance_map.get(interaction_type.lower(), 0)
        
        # If we have a high rating, boost the relevance
        if rating and rating >= 4:
            base_rel += 1
            
        return base_rel

    def _create_feature_vector(
        self,
        user_features: Dict,
        place_features: Dict,
        ncf_score: float,
        content_score: float,
        context_features: Optional[Dict] = None
    ) -> np.ndarray:
        """
        Travel-specific feature engineering (Ported from earlier version).
        Ensures consistency in how data is processed.
        """
        features = []
        
        # User & Budget
        age = float(user_features.get('age', 30))
        features.append(min(age / 100.0, 1.0))
        
        # budget_map = {'low': 0.25, 'medium': 0.5, 'high': 0.75, 'luxury': 1.0}
        # user_budget_val = budget_map.get(user_features.get('budget', 'medium'), 0.5)
        # features.append(user_budget_val)
        
        companion_map = {'solo': 0.1, 'couple': 0.3, 'family': 0.5, 'friends': 0.7, 'business': 0.9}
        features.append(companion_map.get(user_features.get('companion_type', 'solo'), 0.1))
        
        # Place Stats
        features.append(float(place_features.get('avg_rating', 0)) / 5.0)
        features.append(min(float(place_features.get('popularity_score', 0)) / 100.0, 1.0))
        
        # Heuristic Matches
        # place_cost_norm = min(float(place_features.get('avg_cost', 0)) / 1000.0, 1.0)
        # features.append(1.0 - abs(user_budget_val - place_cost_norm))
        
        # crowd_map = {'quiet': 0.25, 'moderate': 0.5, 'busy': 0.75, 'very_busy': 1.0}
        # place_crowd = crowd_map.get(place_features.get('crowd_level', 'moderate'), 0.5)
        # user_crowd_pref = crowd_map.get(user_features.get('preferred_crowd_level', 'moderate'), 0.5)
        # features.append(1.0 - abs(place_crowd - user_crowd_pref))
        
        # Model Scores
        features.append(float(ncf_score))
        features.append(float(content_score))
        features.append((float(ncf_score) + float(content_score)) / 2.0)
        
        # Content Matching
        user_prefs = set(user_features.get('preferences', []))
        place_category = place_features.get('category', '')
        place_tags = set(place_features.get('tags', []))
        features.append(1.0 if place_category in user_prefs else 0.0)
        
        intersect = user_prefs.intersection(place_tags)
        features.append(len(intersect) / max(len(user_prefs), 1))
        
        # Context
        ctx = context_features or {}
        dist = float(ctx.get('distance_km', 10.0))
        features.append(max(0.0, 1.0 - (dist / 50.0)))
        features.append(float(ctx.get('hour', 12)) / 24.0)
        features.append(float(ctx.get('weather_score', 0.8)))
        
        return np.array(features)

    def prepare_training_data(
        self,
        grouped_samples: List[Dict]
    ) -> Tuple[np.ndarray, np.ndarray, List[int]]:
        """
        Organizes training data into a format LightGBM understands.
        Each dictionary in grouped_samples represents one "query" or "user session".
        """
        X, y, group = [], [], []

        for session in grouped_samples:
            items = session.get("items", [])
            if not items:
                continue
            
            group.append(len(items))
            user_features = session["user_features"]
            
            for item in items:
                feat = self._create_feature_vector(
                    user_features=user_features,
                    place_features=item['place_features'],
                    ncf_score=item.get('ncf_score', 0.0),
                    content_score=item.get('content_score', 0.0),
                    context_features=item.get('context_features')
                )
                X.append(feat)
                # Relevance should be an integer for LambdaRank (e.g., 0-4)
                y.append(int(item["relevance_level"])) 

        return np.array(X), np.array(y), group

    def fit(self, grouped_samples: List[Dict]):
        """Train the LambdaRank model."""
        X, y, group = self.prepare_training_data(grouped_samples)
        
        self.model.fit(
            X, y, 
            group=group,
            feature_name=self.feature_names
        )
        self.is_fitted = True
        return self.get_feature_importances()

    def rank_candidates(
        self,
        user_features: Dict,
        candidates: List[Dict]
    ) -> List[Tuple[Union[int, str], float]]:
        """Rank candidates for a specific user."""
        if not self.is_fitted:
            raise ValueError("Model not trained")

        X = []
        ids = []
        for cand in candidates:
            feat = self._create_feature_vector(
                user_features=user_features,
                place_features=cand['place_features'],
                ncf_score=cand.get('ncf_score', 0.0),
                content_score=cand.get('content_score', 0.0),
                context_features=cand.get('context_features')
            )
            X.append(feat)
            ids.append(cand['place_id'])

        scores = self.model.predict(np.array(X))
        ranked = sorted(zip(ids, scores), key=lambda x: x[1], reverse=True)
        return ranked

    def get_feature_importances(self) -> Dict[str, float]:
        if not self.is_fitted:
            return {}
        return dict(zip(self.feature_names, self.model.feature_importances_))

    def save(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({'model': self.model, 'is_fitted': self.is_fitted}, f)

    def load(self, path: str):
        with open(path, "rb") as f:
            data = pickle.load(f)
            self.model = data['model']
            self.is_fitted = data['is_fitted']
            
# import numpy as np
# import pandas as pd
# import lightgbm as lgb
# from typing import List, Tuple
# import logging
# from config.settings import get_settings

# logger = logging.getLogger(__name__)


# class RankingModel:
#     """
#     LightGBM LambdaRank model for learning-to-rank
#     """

#     def __init__(self):
#         self.settings = get_settings()
#         self.model: lgb.Booster | None = None
#         self.feature_columns: List[str] = []

#     # --------------------------------------------------
#     # Data preparation
#     # --------------------------------------------------
#     def prepare_training_data(
#         self,
#         candidates_df: pd.DataFrame,
#         labels: pd.Series
#     ) -> Tuple[pd.DataFrame, pd.Series, np.ndarray]:
#         """
#         Prepare features, labels, and query groups

#         REQUIRED columns:
#         - user_id
#         """

#         feature_cols = [
#             'content_score', 'collaborative_score',
#             'avg_rating', 'popularity_score', 'avg_cost',
#             'crowd_level_encoded', 'category_encoded', 'tag_count',
#             'budget_match', 'crowd_match', 'preference_match',
#             'distance_km',
#             'category_familiarity', 'was_skipped',
#             'hour', 'is_weekend'
#         ]

#         self.feature_columns = [c for c in feature_cols if c in candidates_df.columns]

#         df = candidates_df.copy()
#         df['label'] = labels

#         # CRITICAL: sort by query id
#         df = df.sort_values('user_id')

#         X = df[self.feature_columns].fillna(0)
#         y = df['label']

#         # Query groups
#         group = df.groupby('user_id').size().values

#         return X, y, group

#     # --------------------------------------------------
#     # Training
#     # --------------------------------------------------
#     def fit(
#         self,
#         X_train: pd.DataFrame,
#         y_train: pd.Series,
#         group_train: np.ndarray
#     ):
#         logger.info("Training LambdaRank model")

#         train_data = lgb.Dataset(
#             X_train,
#             label=y_train,
#             group=group_train
#         )

#         params = {
#             'objective': 'lambdarank',
#             'metric': 'ndcg',
#             'ndcg_eval_at': [5, 10],
#             'learning_rate': self.settings.LGBM_LEARNING_RATE,
#             'num_leaves': self.settings.LGBM_NUM_LEAVES,
#             'min_data_in_leaf': 30,
#             'feature_fraction': 0.8,
#             'bagging_fraction': 0.8,
#             'bagging_freq': 5,
#             'verbosity': -1,
#             'random_state': 42
#         }

#         self.model = lgb.train(
#             params,
#             train_data,
#             num_boost_round=self.settings.LGBM_N_ESTIMATORS,
#             callbacks=[
        
#                 lgb.log_evaluation(10)
#             ]
#         )

#         logger.info("Ranking model trained")

#         fi = pd.DataFrame({
#             'feature': self.feature_columns,
#             'importance': self.model.feature_importance(importance_type='gain')
#         }).sort_values('importance', ascending=False)

#         logger.info(f"Top features:\n{fi.head(10)}")

#     # --------------------------------------------------
#     # Inference
#     # --------------------------------------------------
#     def predict(self, X: pd.DataFrame) -> np.ndarray:
#         if self.model is None:
#             raise RuntimeError("Model not trained")

#         X_copy = X.copy()

#         for col in self.feature_columns:
#             if col not in X_copy.columns:
#                 X_copy[col] = 0

#         X_copy = X_copy[self.feature_columns].fillna(0)
#         return self.model.predict(X_copy)

#     def rank_candidates(self, candidates_df: pd.DataFrame) -> pd.DataFrame:
#         scores = self.predict(candidates_df)

#         ranked = candidates_df.copy()
#         ranked['ranking_score'] = scores

#         return ranked.sort_values(
#             ['user_id', 'ranking_score'],
#             ascending=[True, False]
#         )

#     # --------------------------------------------------
#     # Persistence
#     # --------------------------------------------------
#     def save_model(self, filepath: str):
#         if self.model:
#             self.model.save_model(filepath)
#             logger.info(f"Model saved to {filepath}")

#     def load_model(self, filepath: str):
#         self.model = lgb.Booster(model_file=filepath)
#         logger.info(f"Model loaded from {filepath}")
        
# # # ml/ranker.py
# # import numpy as np
# # import pandas as pd
# # import lightgbm as lgb
# # from typing import List, Tuple, Optional
# # import logging
# # from config.settings import get_settings

# # logger = logging.getLogger(__name__)


# # class LambdaRankModel:
# #     """
# #     LightGBM LambdaRank model for learning-to-rank
# #     """

# #     def __init__(self):
# #         self.settings = get_settings()
# #         self.model = None
# #         self.feature_columns: List[str] = []

# #     # ------------------------------------------------------------------
# #     # Feature preparation
# #     # ------------------------------------------------------------------
# #     def prepare_training_data(
# #         self,
# #         candidates_df: pd.DataFrame,
# #         labels: pd.Series
# #     ) -> Tuple[pd.DataFrame, pd.Series, np.ndarray]:
# #         """
# #         Prepare features, labels, and query groups for LambdaRank

# #         REQUIRED columns in candidates_df:
# #         - user_id
# #         - feature columns

# #         Returns:
# #             X : feature matrix
# #             y : relevance labels (graded)
# #             group : query group sizes (per user)
# #         """

# #         features = candidates_df.copy()

# #         feature_cols = [
# #             # Candidate generation scores
# #             'content_score', 'collaborative_score',

# #             # Place features
# #             'avg_rating', 'popularity_score', 'avg_cost',
# #             'crowd_level_encoded', 'category_encoded', 'tag_count',

# #             # User-place matching
# #             'budget_match', 'crowd_match',
# #             'preference_match', 'distance_km',

# #             # Historical behavior
# #             'category_familiarity', 'was_skipped',

# #             # Context
# #             'hour', 'is_weekend'
# #         ]

# #         self.feature_columns = [c for c in feature_cols if c in features.columns]

# #         # Sort by user_id to create valid query groups
# #         features['label'] = labels
# #         features = features.sort_values('user_id')

# #         X = features[self.feature_columns].fillna(0)
# #         y = features['label']

# #         # Query groups (number of candidates per user)
# #         group = features.groupby('user_id').size().values

# #         return X, y, group

# #     # ------------------------------------------------------------------
# #     # Training
# #     # ------------------------------------------------------------------
# #     def fit(
# #         self,
# #         X_train: pd.DataFrame,
# #         y_train: pd.Series,
# #         group_train: np.ndarray,
# #         X_val: pd.DataFrame = None,
# #         y_val: pd.Series = None,
# #         group_val: np.ndarray = None
# #     ):
# #         """
# #         Train LambdaRank model
# #         """

# #         logger.info("Training LambdaRank model")

# #         train_data = lgb.Dataset(
# #             X_train,
# #             label=y_train,
# #             group=group_train
# #         )

# #         valid_sets = [train_data]
# #         valid_names = ['train']

# #         if X_val is not None and y_val is not None and group_val is not None:
# #             val_data = lgb.Dataset(
# #                 X_val,
# #                 label=y_val,
# #                 group=group_val,
# #                 reference=train_data
# #             )
# #             valid_sets.append(val_data)
# #             valid_names.append('valid')

# #         params = {
# #             'objective': 'lambdarank',
# #             'metric': 'ndcg',
# #             'ndcg_eval_at': [5, 10],
# #             'learning_rate': self.settings.LGBM_LEARNING_RATE,
# #             'num_leaves': self.settings.LGBM_NUM_LEAVES,
# #             'min_data_in_leaf': 30,
# #             'feature_fraction': 0.8,
# #             'bagging_fraction': 0.8,
# #             'bagging_freq': 5,
# #             'verbosity': -1,
# #             'random_state': 42
# #         }

# #         self.model = lgb.train(
# #             params,
# #             train_data,
# #             num_boost_round=self.settings.LGBM_N_ESTIMATORS,
# #             valid_sets=valid_sets,
# #             valid_names=valid_names,
# #             callbacks=[
# #                 lgb.early_stopping(stopping_rounds=20),
# #                 lgb.log_evaluation(period=10)
# #             ]
# #         )

# #         logger.info("LambdaRank model trained successfully")

# #         # Feature importance
# #         importance = self.model.feature_importance(importance_type='gain')
# #         fi = pd.DataFrame({
# #             'feature': self.feature_columns,
# #             'importance': importance
# #         }).sort_values('importance', ascending=False)

# #         logger.info(f"Top features:\n{fi.head(10)}")

# #     # ------------------------------------------------------------------
# #     # Inference
# #     # ------------------------------------------------------------------
# #     def predict(self, X: pd.DataFrame) -> np.ndarray:
# #         """
# #         Predict ranking scores
        
# #         Args:
# #             X: Feature dataframe
            
# #         Returns:
# #             Array of ranking scores
# #         """

# #         if self.model is None:
# #             raise RuntimeError("Model not trained")

# #         # Ensure all feature columns exist
# #         for col in self.feature_columns:
# #             if col not in X.columns:
# #                 X[col] = 0

# #         X = X[self.feature_columns].fillna(0)
# #         return self.model.predict(X)

# #     def rank_candidates(
# #         self,
# #         candidates_df: pd.DataFrame,
# #         group_size: Optional[List[int]] = None
# #     ) -> np.ndarray:
# #         """
# #         Rank candidates and return scores
        
# #         Args:
# #             candidates_df: DataFrame with candidate features
# #             group_size: Optional list of group sizes (not used in inference, 
# #                        but kept for API compatibility)
        
# #         Returns:
# #             Array of ranking scores
# #         """
        
# #         if self.model is None:
# #             logger.warning("Model not trained, returning zeros")
# #             return np.zeros(len(candidates_df))
        
# #         # Simply predict scores
# #         return self.predict(candidates_df)

# #     # ------------------------------------------------------------------
# #     # Persistence
# #     # ------------------------------------------------------------------
# #     def save_model(self, filepath: str):
# #         """Save model and feature columns"""
# #         import joblib
        
# #         model_data = {
# #             'model': self.model,
# #             'feature_columns': self.feature_columns
# #         }
        
# #         # Save LightGBM model separately
# #         if self.model is not None:
# #             self.model.save_model(f"{filepath}.lgb")
        
# #         # Save metadata
# #         joblib.dump(model_data, filepath)
# #         logger.info(f"LambdaRank model saved to {filepath}")

# #     def load_model(self, filepath: str):
# #         """Load model and feature columns"""
# #         import joblib
        
# #         # Load metadata
# #         model_data = joblib.load(filepath)
# #         self.feature_columns = model_data['feature_columns']
        
# #         # Load LightGBM model
# #         self.model = lgb.Booster(model_file=f"{filepath}.lgb")
# #         logger.info(f"LambdaRank model loaded from {filepath}")
