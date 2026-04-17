from database.connection import get_db_context
from database_models.postgres_model import Place, User, Interaction
from ml.content_based import ContentBasedRecommender

import logging
import pandas as pd
import sys
from utils.exception import TourismRecommenderException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(user_id: int = 1):  # ✅ pass user_id explicitly
    try:
        logger.info("Starting Content-Based Recommendation Pipeline")

        content_filter = ContentBasedRecommender()

        # ------------------ LOAD DATA ------------------
        with get_db_context() as db:
            places = db.query(Place).all()

            if not places:
                logger.error("No places found in database")
                return

            place_data = pd.DataFrame([
                {
                    "place_id": p.place_id,
                    "name": p.name,
                    "category": p.category.value if hasattr(p.category, "value") else p.category,
                    "subcategory": p.subcategory,
                    "city": p.city,
                    "tags": p.tags or [],
                    "description": p.description,
                    "avg_cost": p.avg_cost,
                    "avg_rating": p.avg_rating,
                    "crowd_level": p.crowd_level.value if hasattr(p.crowd_level, "value") else p.crowd_level,
                    "popularity_score": p.popularity_score,
                }
                for p in places
            ])
            interactions = db.query(Interaction).all()
            interaction_df = pd.DataFrame([{
                'user_id': i.user_id,
                'place_id': i.place_id,
                'interaction_type': i.interaction_type.value if hasattr(i.interaction_type, 'value') else i.interaction_type,
                'timestamp': i.timestamp
            } for i in interactions])

            

        logger.info(f"Loaded {len(place_data)} places")

        # ------------------ TRAIN MODEL ------------------
        content_filter.fit(place_data)
        content_filter.save_model("content_filter.pkl")

        # ------------------ USER RECOMMENDATIONS ------------------
        #logger.info(f"Generating recommendations for user_id={user_profile['user_id']}")
        user_preferences={
            "user_id": 123,
            "preferences":['historical', 'nature', 'food'],
            "preferred_crowd_level": "low",
            "companion_type": "family",
            "budget": 500
        }
        
        
        recommendations = content_filter.get_recommendations_for_user(
            user_id=1,  # ✅ correct param + dict
            interactions_df=interaction_df,
            explicit_preferences=user_preferences,
            place_df=place_data,
            top_k=10,
        )

        print("\nTop recommendations:")
        for rank, (place_id, score) in enumerate(recommendations, start=1):
            print(f"{rank}. Place ID: {place_id}, Score: {score:.3f}")

        # ------------------ SIMILAR PLACES ------------------
        sample_place_id = place_data.iloc[0]["place_id"]
        logger.info(f"Finding places similar to place_id={sample_place_id}")

        similar_places = content_filter.get_similar_places(
            place_id=sample_place_id,
            top_k=5,
        )

        print("\nSimilar places:")
        for place_id, score in similar_places:
            print(f"Place ID: {place_id}, Similarity: {score:.3f}")

        logger.info("Content-Based Recommendation Pipeline finished")

    except Exception as e:
        raise TourismRecommenderException(e, sys)

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import logging
from sqlalchemy.orm import Session
from geoalchemy2.functions import ST_DWithin, ST_GeogFromText, ST_Distance

from config.settings import get_settings
from ml.content_based import ContentBasedRecommender


from cache.redis_client import redis_cache, CacheKeys
from database_models.postgres_model import User, Place
from database.connection import get_db
logger = logging.getLogger(__name__)

# class RecommendationPipeline:
#     """
#     Main recommendation pipeline integrating:
#     1. Candidate Generation (Content-based + Collaborative)
#     2. Ranking (LightGBM)
#     3. Re-ranking (Diversity, Freshness, Distance)
#     """
    
#     def __init__(self):
#         self.settings = get_settings()
#         self.content_model = ContentBasedRecommender()

    
#     def generate_candidates(
#         self,
#         user_id: int,
#         user_profile: Dict,
#         db: Session,
#         candidate_pool_size: int = None
#     ) -> pd.DataFrame:
#         """
#         Phase 1: Candidate Generation
#         Combine content-based and collaborative filtering
        
#         Args:
#             user_id: User ID
#             user_profile: User preferences and attributes
#             db: Database session
#             candidate_pool_size: Number of candidates to generate
        
#         Returns:
#             DataFrame of candidate places with initial scores
#         """
#         if candidate_pool_size is None:
#             candidate_pool_size = self.settings.CANDIDATE_POOL_SIZE
        
#         logger.info(f"Generating candidates for user {user_id}")
        
#         # Get available places
#         # Filter by distance if user has location
#         if user_profile.get('latitude') and user_profile.get('longitude'):
#             user_location = f"POINT({user_profile['longitude']} {user_profile['latitude']})"
#             places_query = db.query(Place).filter(
#                 ST_DWithin(
#                     Place.location,
#                     ST_GeogFromText(user_location),
#                     self.settings.DISTANCE_THRESHOLD_KM * 1000  # Convert to meters
#                 )
#             )
        
#         places_df = pd.read_sql(places_query.statement, db.bind)
        
#         if len(places_df) == 0:
#             logger.warning("No places found within distance threshold")
#             return pd.DataFrame()
#         with get_db_context() as db:
#             interactions = db.query(Interaction).all()
#             interaction_df = pd.DataFrame([{
#                 'user_id': i.user_id,
#                 'place_id': i.place_id,
#                 'interaction_type': i.interaction_type.value if hasattr(i.interaction_type, 'value') else i.interaction_type,
#                 'timestamp': i.timestamp
#             } for i in interactions])

#         # Content-based recommendations
#         content_recs = self.content_model.get_recommendations_for_user(
#             user_id=user_id,
#             interactions_df=interaction_df,
#             explicit_preferences=user_profile,
#             places_df=places_df,
#             top_k=candidate_pool_size // 2
#         )
        
        
        
#         # Combine candidates
#         content_dict = {pid: score for pid, score in content_recs}

#         all_place_ids = set(content_dict.keys()) 
        
#         # Create candidate DataFrame
#         candidates = []
#         for place_id in all_place_ids:
#             candidates.append({
#                 'place_id': place_id,
#                 'content_score': content_dict.get(place_id, 0.0),
    
#                 'combined_score': (
#                     content_dict.get(place_id, 0.0) * 0.5 
#                 )
#             })
        
#         candidates_df = pd.DataFrame(candidates)
        
#         # Merge with place features
#         candidates_df = candidates_df.merge(
#             places_df,
#             on='place_id',
#             how='left'
#         )
        
#         # Calculate distance if user has location
#         if user_profile.get('latitude') and user_profile.get('longitude'):
#             from geopy.distance import geodesic
#             candidates_df['distance_km'] = candidates_df.apply(
#                 lambda row: geodesic(
#                     (user_profile['latitude'], user_profile['longitude']),
#                     (row['latitude'], row['longitude'])
#                 ).km,
#                 axis=1
#             )
#         else:
#             candidates_df['distance_km'] = 0
        
#         # Sort by combined score and take top candidates
#         candidates_df = candidates_df.nlargest(candidate_pool_size, 'combined_score')
        
#         logger.info(f"Generated {len(candidates_df)} candidates")
        
#         return candidates_df
    
#     def get_recommendations(
#         self,
#         user_id: int,
#         db: Session,
#         top_k: int = None,
#         context: Dict = None,
#         use_cache: bool = True
#     ) -> List[Dict]:
#         """
#         Main recommendation method
        
#         Args:
#             user_id: User ID
#             db: Database session
#             top_k: Number of recommendations
#             context: Additional context
#             use_cache: Whether to use cache
        
#         Returns:
#             List of recommended places with metadata
#         """
#         if top_k is None:
#             top_k = self.settings.MAX_RECOMMENDATIONS
        
#         # Check cache
#         if use_cache:
#             cache_key = CacheKeys.user_recommendations(user_id)
#             cached = redis_cache.get(cache_key)
#             if cached:
#                 logger.info(f"Cache hit for user {user_id} recommendations")
#                 return cached[:top_k]
        
#         # Get user profile
#         user = db.query(User).filter(User.user_id == user_id).first()
#         if not user:
#             logger.error(f"User {user_id} not found")
#             return []
        
#         user_profile = {
#             'user_id': user_id,
#             'age': user.age,
#             'gender': user.gender,
#             'budget': user.budget,
#             'preferred_crowd_level': user.preferred_crowd_level,
#             'preferences': user.preferences,
#             'companion_type': user.companion_type,
        
#         }
        
#         # Phase 1: Candidate Generation
#         candidates = self.generate_candidates(user_id, user_profile, db)
        

        
#         # Convert to output format
#         recommendations = []
#         for _, row in candidates.iterrows():
#             recommendations.append({
#                 'place_id': int(row['place_id']),
#                 'name': row['name'],
#                 'category': row['category'],
#                 'city': row['city'],
#                 'latitude': float(row['latitude']),
#                 'longitude': float(row['longitude']),
#                 'avg_rating': float(row['avg_rating']) if pd.notna(row['avg_rating']) else None,
#                 'avg_cost': float(row['avg_cost']) if pd.notna(row['avg_cost']) else None,
#                 'distance_km': float(row['distance_km']) if pd.notna(row['distance_km']) else None,
#                 'score': float(row['combined_score']),
#                 'description': row.get('description', '')
#             })
        
#         # Cache results
#         if use_cache:
#             redis_cache.set(
#                 cache_key,
#                 recommendations,
#                 ttl=self.settings.RECOMMENDATION_CACHE_TTL
#             )
        
#         return recommendations
from ml.collaborative import CollaborativeFilteringRecommender
from ml.feature_engineer import FeatureEngineer
from ml.ranker import LambdaRankModel
from database_models.interaction_repository import InteractionRepository
class RecommendationPipeline:

    def __init__(self):
        self.settings = get_settings()
        self.content_model = ContentBasedRecommender()
        self.collaborative_model = CollaborativeFilteringRecommender()
        self.feature_engineer= FeatureEngineer()
        self.ranker=LambdaRankModel()

    def generate_candidates(
        self,
        user_id: int,
        user_profile: Dict,
        db: Session,
        candidate_pool_size: int = None
    ) -> pd.DataFrame:

        if candidate_pool_size is None:
            candidate_pool_size = self.settings.CANDIDATE_POOL_SIZE

        logger.info(f"Generating candidates for user {user_id}")

        # -----------------------------
        # Build place query (DO NOT .all())
        # -----------------------------
        places_query = db.query(Place)

        if user_profile.get('latitude') and user_profile.get('longitude'):
            user_location = f"POINT({user_profile['longitude']} {user_profile['latitude']})"
            places_query = places_query.filter(
                ST_DWithin(
                    Place.location,
                    ST_GeogFromText(user_location),
                    self.settings.DISTANCE_THRESHOLD_KM * 1000
                )
            )

        places_df = pd.read_sql(places_query.statement, db.bind)

        if places_df.empty:
            return pd.DataFrame()

        # -----------------------------
        # FIT content model
        # -----------------------------
        self.content_model.fit(places_df)

        # TODO: replace with real interactions_df
        interactions_df = pd.DataFrame(columns=["user_id", "place_id", "interaction_type", "timestamp"])

        # candidates = [
        #     {
        #         "place_id": pid,
        #         "content_score": score,
        #         "combined_score": score
        #     }
        #     for pid, score in content_recs
        # ]

        # candidates_df = pd.DataFrame(candidates)

        # candidates_df = candidates_df.merge(
        #     places_df,
        #     on="place_id",
        #     how="left"
        # )

        # # Distance calc
        # if user_profile.get('latitude') and user_profile.get('longitude'):
        #     from geopy.distance import geodesic
        #     candidates_df["distance_km"] = candidates_df.apply(
        #         lambda r: geodesic(
        #             (user_profile["latitude"], user_profile["longitude"]),
        #             (r["latitude"], r["longitude"])
        #         ).km,
        #         axis=1
        #     )
        # else:
        #     candidates_df["distance_km"] = 0.0

        # return candidates_df.nlargest(candidate_pool_size, "combined_score")
        
        content_recs = self.content_model.get_recommendations_for_user(
            user_id=user_id,
            interactions_df=interactions_df,
            explicit_preferences=user_profile,
            place_df=places_df,
            top_k=candidate_pool_size
        )

        # Collaborative filtering recommendations
        collab_recs = self.collaborative_model.get_recommendations(
            user_id=user_id,
            top_k=candidate_pool_size // 2
        )
        
        # Combine candidates
        content_dict = {pid: score for pid, score in content_recs}
        collab_dict = {pid: score for pid, score in collab_recs}
        
        all_place_ids = set(content_dict.keys()) | set(collab_dict.keys())
        
        # Create candidate DataFrame
        candidates = []
        for place_id in all_place_ids:
            candidates.append({
                'place_id': place_id,
                'content_score': content_dict.get(place_id, 0.0),
                'collaborative_score': collab_dict.get(place_id, 0.0),
                'combined_score': (
                    content_dict.get(place_id, 0.0) * 0.9 +
                    collab_dict.get(place_id, 0.0) * 0.1
                )
            })
        
        candidates_df = pd.DataFrame(candidates)
        
        # Merge with place features
        candidates_df = candidates_df.merge(
            places_df,
            on='place_id',
            how='left'
        )
        
        # Calculate distance if user has location
        if user_profile.get('latitude') and user_profile.get('longitude'):
            from geopy.distance import geodesic
            candidates_df['distance_km'] = candidates_df.apply(
                lambda row: geodesic(
                    (user_profile['latitude'], user_profile['longitude']),
                    (row['latitude'], row['longitude'])
                ).km,
                axis=1
            )
        else:
            candidates_df['distance_km'] = 0
        
        # Sort by combined score and take top candidates
        candidates_df = candidates_df.nlargest(candidate_pool_size, 'combined_score')
        
        logger.info(f"Generated {len(candidates_df)} candidates")
        
        return candidates_df
    
    # def rank_candidates(
    #     self,
    #     candidates_df: pd.DataFrame,
    #     user_id: int,
    #     user_profile: Dict,
    #     context: Dict = None
    # ) -> pd.DataFrame:
    #     """
    #     Phase 2: Ranking
    #     Use LightGBM to re-score candidates
        
    #     Args:
    #         candidates_df: Candidate places
    #         user_id: User ID
    #         user_profile: User attributes
    #         context: Additional context (time, device, etc.)
        
    #     Returns:
    #         Ranked DataFrame
    #     """
    #     if len(candidates_df) == 0:
    #         return candidates_df
        
    #     logger.info(f"Ranking {len(candidates_df)} candidates")
        
    #     # Add user features
    #     # for key, value in user_profile.items():
    #     #     if key not in candidates_df.columns:
    #     #         candidates_df[f'traveler_{key}'] = value
    #     for key, value in user_profile.items():
    #         # Only inject scalar values
    #         if isinstance(value, (int, float, str, bool)):
    #             candidates_df[f'user_{key}'] = value

    #     # Add context features
    #     if context:
    #         now = datetime.utcnow()
    #         candidates_df['hour'] = context.get('hour', now.hour)
    #         candidates_df['day_of_week'] = context.get('day_of_week', now.weekday())
    #         candidates_df['is_weekend'] = candidates_df['day_of_week'].isin([5, 6]).astype(int)
        
    #     # Get interaction history
    #     with get_db_context() as db:
                
    #         interaction_history = InteractionRepository.get_user_history(user_id=user_id,db=db, days=90)
    #         interaction_df = pd.DataFrame(interaction_history)
            
    #     # Engineer features
    #     if not interaction_df.empty:
    #         candidates_df = self.feature_engineer.create_ranking_features(
    #             candidates_df,
    #             user_id,
    #             interaction_df
    #         )
    #     else:
    #         candidates_df['category_familiarity'] = 0
    #         candidates_df['was_skipped'] = 0
        
    #     # Calculate match features
    #     candidates_df['budget_match'] = (
    #         (user_profile.get('budget', 0) >= candidates_df['avg_cost'] * 0.5) &
    #         (user_profile.get('budget', float('inf')) <= candidates_df['avg_cost'] * 2)
    #     ).astype(int)
        
    #     candidates_df['preference_match'] = candidates_df['category'].apply(
    #         lambda cat: 1 if cat in user_profile.get('preferences', []) else 0
    #     )
        
    #     # Position feature
    #     candidates_df['candidate_position_normalized'] = np.arange(len(candidates_df)) / len(candidates_df)
        
    #     # Rank using model
    #     ranked_df = self.ranker.rank_candidates(candidates_df)
        
    #     logger.info("Candidates ranked")
    #     print(ranked_df)
    #     return ranked_df
    
    
    

    def get_recommendations(
        self,
        user_id: int,
        db: Session,
        top_k: int = None,
        context: Dict = None,
        use_cache: bool = True
    ) -> List[Dict]:

        if top_k is None:
            top_k = self.settings.MAX_RECOMMENDATIONS

        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return []

        user_profile = {
            "user_id": user_id,
            "age": user.age,
            "gender": user.gender,
            # "budget": user.budget,
            # "preferred_crowd_level": user.preferred_crowd_level,
            "preferences": user.preferences,
            "companion_type": user.companion_type,
        }

        # Merge context
        if context:
            user_profile.update(context)

        candidates = self.generate_candidates(user_id, user_profile, db)
      #  ranked = self.rank_candidates(candidates, user_id, user_profile, context)

        recommendations = []
        for _, row in candidates.head(top_k).iterrows():
            recommendations.append({
                "place_id": int(row["place_id"]),
                "name": row["name"],
                "category": row["category"],
                "city": row["city"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "avg_rating": float(row["avg_rating"]) if pd.notna(row["avg_rating"]) else None,
               # "avg_cost": float(row["avg_cost"]) if pd.notna(row["avg_cost"]) else None,
                "distance_km": float(row["distance_km"]),
                "score": float(row["combined_score"]),
                "description": row.get("description", "")
            })

        return recommendations
    

if __name__ == "__main__":
   # main(user_id=1)  # ✅ change user_id as needed
    a=RecommendationPipeline()

    with get_db_context() as db:
        candidates=a.get_recommendations(user_id=1,db=db,top_k=20,context= {
                    'type': 'coordinates',
                    'latitude': 19.099693,
                    'longitude':72.946123,
                    'source': 'gps'
                })
    for c in candidates:    
        print(c['place_id'],c['category'],c['latitude'],c['score'],c['city'])



# # #collaborative:
# import pandas as pd
# import logging
# from ml.collaborative import CollaborativeFilteringRecommender

# logging.basicConfig(level=logging.INFO)

# def main():
#     # -----------------------------
#     # 1. Load interaction data
#     # -----------------------------
#     # Expected columns: user_id, item_id, rating (or implicit feedback like count)
#     data = pd.read_csv("data/data_interactions.csv")

#     print("Sample input data:")
#     print(data.head())

#     # -----------------------------
#     # 2. Initialize recommender
#     # -----------------------------
#     recommender = CollaborativeFilteringRecommender()

#     # -----------------------------
#     # 3. Fit model (ONLY ONCE)
#     # -----------------------------
#     recommender.fit(data)
    
#     print("\nModel trained successfully!")

#     # -----------------------------
#     # 4. Test recommendations
#     # -----------------------------
#     test_user_id = data["user_id"].iloc[0]

#     recommendations = recommender.get_recommendations(
#         user_id=test_user_id
#     )

#     print(f"\nTop recommendations for user {test_user_id}:")
#     for item_id, score in recommendations:
#         print(f"Item: {item_id}, Score: {score:.4f}")

#     # -----------------------------
#     # 5. Similar items check (optional)
#     # -----------------------------
#     test_item_id = data["place_id"].iloc[0]

#     similar_items = recommender.get_similar_places(
#         place_id=test_item_id
#     )

#     print(f"\nItems similar to item {test_item_id}:")
#     for item_id, score in similar_items:
#         print(f"Item: {item_id}, Similarity: {score:.4f}")


# if __name__ == "__main__":
#     main()

# #save model load model no.of candidates location question 

# import pandas as pd
# import numpy as np

# #from ml.ranker import RankingModel


# def main():
#     # -----------------------------
#     # 1. Create dummy candidate data
#     # -----------------------------
#     num_users = 3
#     candidates_per_user = 5

#     rows = []
#     labels = []

#     for user_id in range(num_users):
#         for i in range(candidates_per_user):
#             rows.append({
#                 "user_id": user_id,

#                 # Candidate generation scores
#                 "content_score": np.random.rand(),
#                 "collaborative_score": np.random.rand(),

#                 # Place features
#                 "avg_rating": np.random.uniform(3.0, 5.0),
#                 "popularity_score": np.random.rand(),
#                 "avg_cost": np.random.randint(200, 2000),
#                 "crowd_level_encoded": np.random.randint(0, 3),
#                 "category_encoded": np.random.randint(0, 5),
#                 "tag_count": np.random.randint(1, 6),

#                 # User-place matching
#                 "budget_match": np.random.randint(0, 2),
#                 "crowd_match": np.random.randint(0, 2),
#                 "preference_match": np.random.randint(0, 2),
#                 "distance_km": np.random.uniform(0.5, 25),

#                 # Historical behavior
#                 "category_familiarity": np.random.rand(),
#                 "was_skipped": np.random.randint(0, 2),

#                 # Context
#                 "hour": np.random.randint(0, 24),
#                 "is_weekend": np.random.randint(0, 2),
#             })

#             # Relevance labels (0–3 for LambdaRank)
#             labels.append(np.random.randint(0, 4))

#     candidates_df = pd.DataFrame(rows)
#     labels = pd.Series(labels)

#     print("Candidates DF shape:", candidates_df.shape)
#     print("Labels shape:", labels.shape)

    # -----------------------------
    # 2. Train LambdaRank model
    # -----------------------------
#     ranker = RankingModel()

#     X, y, group = ranker.prepare_training_data(
#         candidates_df=candidates_df,
#         labels=labels
#     )

#     ranker.fit(
#         X_train=X,
#         y_train=y,
#         group_train=group
#     )

#     # -----------------------------
#     # 3. Rank candidates (inference)
#     # -----------------------------
#    # scores = ranker.rank_candidates(candidates_df)

#     # Merge scores back to DataFrame
#     ranked_df = candidates_df.copy()
#     ranked_df["rank_score"] = scores

#     ranked_df = ranked_df.sort_values(
#         ["user_id", "rank_score"],
#         ascending=[True, False]
#     )

    # -----------------------------
    # 4. Display results
    # -----------------------------
#     print("\nTop recommendations per user:\n")

#     for user_id, group_df in ranked_df.groupby("user_id"):
#         print(f"User {user_id}")
#         print(
#             group_df[[
#                 "rank_score",
#                 "content_score",
#                 "collaborative_score",
#                 "avg_rating",
#                 "distance_km"
#             ]].head(3)
#         )
#         print("-" * 40)


# if __name__ == "__main__":
#     main()


# import numpy as np
# import pandas as pd

# from ml.ranker import RankingModel


# # --------------------------------------------------
# # Relevance label generator (simulated user behavior)
# # --------------------------------------------------
# def generate_relevance(row) -> int:
#     """
#     Deterministic graded relevance: 0–3
#     """
#     score = (
#         0.4 * row["content_score"] +
#         0.4 * row["collaborative_score"] +
#         0.2 * row["preference_match"]
#     )

#     if score >= 0.75:
#         return 3
#     elif score >= 0.55:
#         return 2
#     elif score >= 0.35:
#         return 1
#     return 0

# import numpy as np
# def main():
#     np.random.seed(42)

#     # --------------------------------------------------
#     # 1. Generate synthetic candidate data
#     # --------------------------------------------------
#     num_users = 50
#     candidates_per_user = 20

#     rows = []

#     for user_id in range(num_users):
#         for _ in range(candidates_per_user):
#             rows.append({
#                 "user_id": user_id,

#                 # Candidate generation
#                 "content_score": np.random.rand(),
#                 "collaborative_score": np.random.rand(),

#                 # Place features
#                 "avg_rating": np.random.uniform(3.0, 5.0),
#                 "popularity_score": np.random.rand(),
#                 "avg_cost": np.random.randint(300, 3000),
#                 "crowd_level_encoded": np.random.randint(0, 3),
#                 "category_encoded": np.random.randint(0, 6),
#                 "tag_count": np.random.randint(1, 8),

#                 # User-place match
#                 "budget_match": np.random.randint(0, 2),
#                 "crowd_match": np.random.randint(0, 2),
#                 "preference_match": np.random.randint(0, 2),
#                 "distance_km": np.random.uniform(0.5, 30),

#                 # History
#                 "category_familiarity": np.random.rand(),
#                 "was_skipped": np.random.randint(0, 2),

#                 # Context
#                 "hour": np.random.randint(0, 24),
#                 "is_weekend": np.random.randint(0, 2),
#             })

#     candidates_df = pd.DataFrame(rows)

#     # --------------------------------------------------
#     # 2. Generate relevance labels
#     # --------------------------------------------------
#     labels = candidates_df.apply(generate_relevance, axis=1)

#     print("Samples:", len(candidates_df))
#     print("Label distribution:")
#     print(labels.value_counts().sort_index())

#     # --------------------------------------------------
#     # 3. Train ranking model
#     # --------------------------------------------------
#     model = RankingModel()

#     X, y, group = model.prepare_training_data(
#         candidates_df=candidates_df,
#         labels=labels
#     )

#     model.fit(
#         X_train=X,
#         y_train=y,
#         group_train=group
#     )

#     # --------------------------------------------------
#     # 4. Rank candidates
#     # --------------------------------------------------
#     ranked_df = model.rank_candidates(candidates_df)

#     scores = ranked_df["ranking_score"].values
#     print("\nPrediction variance:", np.var(scores))

#     # --------------------------------------------------
#     # 5. Display top results
#     # --------------------------------------------------
#     for user_id, group_df in ranked_df.groupby("user_id"):
#         print(f"\nUser {user_id} — Top 3 recommendations")
#         print(
#             group_df[[
#                 "ranking_score",
#                 "content_score",
#                 "collaborative_score",
#                 "preference_match",
#                 "avg_rating",
#                 "distance_km"
#             ]].head(3)
#         )

#         # Keep output readable
#         if user_id == 2:
#             break


# if __name__ == "__main__":
#     main()
