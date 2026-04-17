import numpy as np
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from pathlib import Path
import torch

from config.settings import get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from database_models.postgres_model import User, Place, Interaction, PrecomputedCandidate
from geoalchemy2.functions import ST_Distance, ST_GeogFromText

settings = get_settings()

from ml.collaborative import CollaborativeFilteringRecommender
from ml.content_based import ContentBasedRecommender
from ml.ranker import LambdaRankModel  
from ml.re_ranking import ReRanker  
from services.cache import RedisCache
import pandas as pd

class RecommendationService:
    def __init__(self):
        self.cf_model: Optional[CollaborativeFilteringRecommender] = None
        self.content_filter: Optional[ContentBasedRecommender] = None
        self.ranker: Optional[LambdaRankModel] = None
        self.reranker = ReRanker()
        self.models_loaded = False
    
    def load_models(self):
        """Load all trained models"""
        # Load ALS model
        if Path(settings.ALS_MODEL_PATH).exists():
            self.cf_model = CollaborativeFilteringRecommender()
            self.cf_model.load_model(settings.ALS_MODEL_PATH)
        
        # Load content-based filter
        if Path(settings.CONTENT_MODEL_PATH).exists():
            self.content_filter = ContentBasedRecommender()
            self.content_filter.load_model(settings.CONTENT_MODEL_PATH)
        
        if Path(settings.LAMBDARANK_MODEL_PATH).exists():
            self.ranker = LambdaRankModel()
            self.ranker.load(settings.LAMBDARANK_MODEL_PATH)

        
        self.models_loaded = True
    
    async def generate_candidates(
    self,
    db: AsyncSession,
    cache: RedisCache,
    user_id: int,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    force_refresh: bool = False
     )-> List[Dict]:
        """Generate candidates using ALS + Content-Based"""
        
        # ... cache check code ...
        
        # Get user data
        result = await db.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return []
        
        # Get interactions for both models
        interactions_result = await db.execute(
            select(Interaction).where(Interaction.user_id == user_id)
        )
        interactions = interactions_result.scalars().all()
        
        # Convert to DataFrame for models
        interactions_df = pd.DataFrame([
            {
                'user_id': i.user_id,
                'place_id': i.place_id,
                'interaction_type': i.interaction_type.value,
                'timestamp': i.timestamp
            }
            for i in interactions
        ])
        
        # Get all places
        # places_result = await db.execute(select(Place))
        # places = places_result.scalars().all()
        from geoalchemy2.functions import ST_DWithin

        places_query = select(Place)

        if latitude and longitude:
            user_point = f"POINT({longitude} {latitude})"

            places_query = places_query.where(
                ST_DWithin(
                    Place.location,
                    ST_GeogFromText(user_point),
                    settings.DISTANCE_THRESHOLD_KM * 1000
                )
            )

        places_result = await db.execute(places_query)
        places = places_result.scalars().all()

        places_df = pd.DataFrame([
            {
                'place_id': p.place_id,
                'category': p.category,
               # 'subcategory': p.category,  # Add if you have this
                'tags': p.tags,
                'city': p.city,
                # 'crowd_level': p.crowd_level.value if p.crowd_level else None,
                # 'avg_cost': p.avg_cost,
                'avg_rating': p.avg_rating,
                'description': p.description,
                'popularity_score': p.popularity_score
            }
            for p in places
        ])
        
        candidates = []
        
        # 1. ALS scores
        als_scores = {}
        if self.cf_model and self.models_loaded:
            try:
                als_results = self.cf_model.get_recommendations(
                    user_id=user_id,
                    top_k=200
                )
                als_scores = dict(als_results)
            except Exception as e:
                print(f"Error computing ALS scores: {e}")
        
        # 2. Content-based scores
        content_scores = {}
        if self.content_filter and self.models_loaded:
            try:
                # Build user preferences
                user_prefs = {
                    'user_id': user_id,
                    'preferences': user.preferences or [],
                    # 'budget': user.budget,
                    # 'preferred_crowd_level': user.preferred_crowd_level.value if user.preferred_crowd_level else None,
                    'companion_type': user.companion_type.value if user.companion_type else None
                }
                
                content_results = self.content_filter.get_recommendations_for_user(
                    user_id=user_id,
                    interactions_df=interactions_df,
                    explicit_preferences=user_prefs,
                    place_df=places_df,
                    top_k=200
                )
                
                content_scores = dict(content_results)
            except Exception as e:
                print(f"Error computing content scores: {e}")
        
        # 3. Combine scores
        #all_place_ids = set(als_scores.keys()) | set(content_scores.keys())
        # Only allow places that passed spatial filtering
        valid_place_ids = set(places_df['place_id'].tolist())

        filtered_als_scores = {
            pid: score for pid, score in als_scores.items()
            if pid in valid_place_ids
        }

        filtered_content_scores = {
            pid: score for pid, score in content_scores.items()
            if pid in valid_place_ids
        }

        all_place_ids = set(filtered_als_scores.keys()) | set(filtered_content_scores.keys())
        for place_id in all_place_ids:
            als_score = filtered_als_scores.get(place_id, 0.0)
            content_score = filtered_content_scores.get(place_id, 0.0)

        # for place_id in all_place_ids:
        #     als_score = als_scores.get(place_id, 0.0)
        #     content_score = content_scores.get(place_id, 0.0)
            
            # Weighted average (tune these weights)
            combined_score = 0.4 * als_score + 0.6 * content_score
            
            candidates.append({
                'place_id': place_id,
                'als_score': float(als_score),
                'content_score': float(content_score),
                'combined_score': float(combined_score)
            })
        
        # Sort and take top N
        candidates.sort(key=lambda x: x['combined_score'], reverse=True)
        candidates = candidates[:settings.CANDIDATE_POOL_SIZE]
        
        # Cache
        await cache.cache_user_candidates(user_id, candidates)
        
        return candidates
     
    async def rank_candidates(
        self,
        db, # AsyncSession
        user_id: int,
        candidates: List[Dict],
        context: Optional[Dict] = None,
        # user_model = None, # User SQLAlchemy Model
        # place_model = None  # Place SQLAlchemy Model
    ) -> List[Tuple[int, float]]:
        """
        Asynchronous wrapper to rank candidates using the model.
        This method handles DB lookups and formatting.
        """
        # 1. Check Model State
        if not self.ranker or not self.models_loaded:
            # Fallback to a weighted average of model scores if ranker isn't ready
            return sorted(
                [(c['place_id'], (c.get('als_score', 0) + c.get('content_score', 0)) / 2) 
                 for c in candidates],
                key=lambda x: x[1], 
                reverse=True
            )

        # 2. Fetch User Features
        # Note: In a real implementation, 'select' and 'user_model' are required
        # For demonstration, we assume standard SQLAlchemy async patterns
        from sqlalchemy.future import select
        
        user_result = await db.execute(select(User).where(User.user_id == user_id))
        user = user_result.scalar_one_or_none()
        
        if not user:
            return []

        user_features = {
            'age': getattr(user, 'age', 30),
            # 'budget': getattr(user, 'budget', 'medium'),
            'companion_type': getattr(user, 'companion_type', 'solo'),
            # 'preferred_crowd_level': getattr(user, 'preferred_crowd_level', 'moderate'),
            'preferences': getattr(user, 'preferences', [])
        }

        # 3. Fetch Place Data for candidates
        place_ids = [c['place_id'] for c in candidates]
        places_result = await db.execute(select(Place).where(Place.place_id.in_(place_ids)))
        places_dict = {p.place_id: p for p in places_result.scalars().all()}

        # 4. Prepare for ranking
        ranking_candidates = []
        for cand in candidates:
            place_id = cand['place_id']
            place = places_dict.get(place_id)
            if not place:
                continue

            place_features = {
                'category': getattr(place, 'category', ''),
                'tags': getattr(place, 'tags', []),
                #'avg_cost': getattr(place, 'avg_cost', 0),
                'avg_rating': getattr(place, 'avg_rating', 0),
                #'crowd_level': getattr(place, 'crowd_level', 'moderate'),
                'popularity_score': getattr(place, 'popularity_score', 0)
            }

            ranking_candidates.append({
                'place_id': place_id,
                'place_features': place_features,
                'als_score': cand.get('als_score', 0.0),
                'content_score': cand.get('content_score', 0.0),
                'context_features': context or {}
            })

        ranked = self.ranker.rank_candidates(user_features, ranking_candidates)

        # 5. Execute Ranking
        return ranked
    
    # async def rank_candidates(
    #     self,
    #     db: AsyncSession,
    #     user_id: int,
    #     candidates: List[Dict],
    #     context: Dict = None
    # ) -> List[Tuple[int, float]]:
    #     """
    #     Rank candidates using LambdaRank
        
    #     Args:
    #         db: Database session
    #         user_id: User ID
    #         candidates: List of candidate dicts
    #         context: Optional context (distance, time, weather)
            
    #     Returns:
    #         List of (place_id, rank_score) tuples
    #     """
    #     if not self.ranker or not self.ranker.is_fitted:
    #         # Fallback to combined scores if ranker not available
    #         return [
    #             (c['place_id'], c['combined_score']) 
    #             for c in candidates
    #         ]
        
    #     # Get user features
    #     result = await db.execute(
    #         select(User).where(User.user_id == user_id)
    #     )
    #     user = result.scalar_one_or_none()
        
    #     if not user:
    #         return []
        
    #     user_features = {
    #         'age': user.age or 30,
    #         'budget': user.budget or 'medium',
    #         'companion_type': user.companion_type or 'solo',
    #         'preferred_crowd_level': user.preferred_crowd_level or 'moderate',
    #         'preferences': user.preferences or []
    #     }
        
    #     # Get place features for candidates
    #     place_ids = [c['place_id'] for c in candidates]
    #     places_result = await db.execute(
    #         select(Place).where(Place.place_id.in_(place_ids))
    #     )
    #     places = places_result.scalars().all()
    #     places_dict = {p.place_id: p for p in places}
        
    #     # Prepare candidates for ranking
    #     ranking_candidates = []
    #     for candidate in candidates:
    #         place_id = candidate['place_id']
    #         place = places_dict.get(place_id)
            
    #         if not place:
    #             continue
            
    #         place_features = {
    #             'category': place.category,
    #             'tags': place.tags or [],
    #             'avg_cost': place.avg_cost or 0,
    #             'avg_rating': place.avg_rating,
    #             'crowd_level': place.crowd_level,
    #             'popularity_score': place.popularity_score
    #         }
            
    #         ranking_candidates.append({
    #             'place_id': place_id,
    #             'place_features': place_features,
    #             'ncf_score': candidate['ncf_score'],
    #             'content_score': candidate['content_score'],
    #             'context_features': context or {}
    #         })
        
    #     # Rank using LambdaRank
    #     ranked = self.ranker.rank_candidates(user_features, ranking_candidates)
        
    #     return ranked

    async def get_recommendations(
        self,
        db: AsyncSession,
        cache: RedisCache,
        user_id: int,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        max_distance_km: Optional[float] = None,
        limit: int = 20,
        category_filter: Optional[List[str]] = None,
        force_refresh: bool = False
    ) -> Dict:
        """
        Get final personalized recommendations
        
        Pipeline:
        1. Generate candidates (ALS + Content-based) [Cached for 1 hour]
        2. Rank candidates (LambdaRank)
        3. Apply filters and return top N
        """
        # Check cache for final recommendations
        request_params = {
            'latitude': latitude,
            'longitude': longitude,
            'max_distance_km': max_distance_km,
            'limit': limit,
            'category_filter': category_filter
        }
        
        if not force_refresh:
            cached_recs = await cache.get_recommendations(user_id, request_params)
            if cached_recs:
                return {
                    **cached_recs,
                    'cache_hit': True
                }
        
        # Stage 1: Generate candidates
        #candidates = await self.generate_candidates(db, cache, user_id, force_refresh)
        candidates = await self.generate_candidates(
        db=db,
    cache=cache,
    user_id=user_id,
    latitude=latitude,
    longitude=longitude,
    force_refresh=force_refresh
)

        if not candidates:
            return {
                'user_id': user_id,
                'recommendations': [],
                'computed_at': datetime.now(),
                'cache_hit': False
            }
        print(candidates)
                # DEBUG: Fetch place details for ALL candidates to inspect fields
        all_candidate_ids = [c['place_id'] for c in candidates]

        places_result = await db.execute(
            select(Place).where(Place.place_id.in_(all_candidate_ids))
        )
        places = places_result.scalars().all()

        print("\n===== CANDIDATE DEBUG INFO =====")
        for place in places:
            print({
                "place_id": place.place_id,
                "city": place.city,
                "latitude": place.latitude,
                "longitude": place.longitude,
                "category": place.category
            })
        print("================================\n")

        # Stage 2: Rank candidates
        context = {}
        if latitude and longitude:
            context['latitude'] = latitude
            context['longitude'] = longitude
        
        ranked = await self.rank_candidates(db, user_id, candidates, context)
        print("ranked____________________",ranked)
        # Get place data for final results
        place_ids = [place_id for place_id, _ in ranked]
        places_result = await db.execute(
            select(Place).where(Place.place_id.in_(place_ids))
        )
        places = places_result.scalars().all()
        places_dict = {p.place_id: p for p in places}
        
        # Apply filters
        final_recommendations = []
        
        for place_id, score in ranked:
            place = places_dict.get(place_id)
            
            if not place:
                continue
            
            # Distance filter
            # if max_distance_km and latitude and longitude:
            #     from geopy.distance import geodesic
            #     distance = geodesic(
            #         (latitude, longitude),
            #         (place.latitude, place.longitude)
            #     ).kilometers
                
            #     if distance > max_distance_km:
            #         continue
            # else:
            #     distance = None
            
            # # Category filter
            # if category_filter and place.category not in category_filter:
            #     continue
        #      Stage 2: DIRECT SORT (No Ranking Model)
        #candidates.sort(key=lambda x: x['combined_score'], reverse=True)

        # Fetch place details
        # place_ids = [c['place_id'] for c in candidates[:limit]]
        # places_result = await db.execute(
        #     select(Place).where(Place.place_id.in_(place_ids))
        # )
        # places = places_result.scalars().all()
        # places_dict = {p.place_id: p for p in places}

        # final_recommendations = []

        # for candidate in candidates[:limit]:
        #     place = places_dict.get(candidate['place_id'])
        #     if not place:
        #         continue
    
            # Build recommendation
            final_recommendations.append({
                'place': {
                    'place_id': place.place_id,
                    'name': place.name,
                    'category': place.category,
                    'city': place.city,
                    'latitude': place.latitude,
                    'longitude': place.longitude,
                    'description': place.description,
                    'tags': place.tags,
                    #'avg_cost': place.avg_cost,
                    'avg_rating': place.avg_rating,
                    #'crowd_level': place.crowd_level.value if place.crowd_level else None,
                    'popularity_score': place.popularity_score,
                    # 'images': place.images,
                    # 'cover_image': place.cover_image,
                  #  'distance_km': distance
                },
               # 'score': float(score),
                'explanation': f"Recommended based on your preferences"
            })
            
            if len(final_recommendations) >= limit:
                break
        print(final_recommendations)
        result = {
            'user_id': user_id,
            'recommendations': final_recommendations,
            'computed_at': datetime.now(),
            'cache_hit': False
        }
        
        # Cache the result
        await cache.cache_recommendations(user_id, request_params, result)
        
        return result



#     async def get_recommendations(
#         self,
#         db: AsyncSession,
#         cache: RedisCache,
#         user_id: int,
#         latitude: Optional[float] = None,
#         longitude: Optional[float] = None,
#         max_distance_km: Optional[float] = None,
#         limit: int = 20,
#         category_filter: Optional[List[str]] = None,
#         force_refresh: bool = False
#     ) -> Dict:
#         """
#         Get final personalized recommendations with complete pipeline
        
#         Pipeline:
#         1. Generate candidates (NCF + Content-based) [Cached for 1 hour]
#         2. Rank candidates (LambdaRank)
#         3. Re-rank with freshness and distance
#         4. Apply filters and return top N
        
#         Args:
#             db: Database session
#             cache: Redis cache
#             user_id: User ID
#             latitude: User's current latitude
#             longitude: User's current longitude
#             max_distance_km: Maximum distance filter
#             limit: Number of recommendations to return
#             category_filter: Optional category filter
#             force_refresh: Force refresh of all caches
            
#         Returns:
#             Dict with recommendations and metadata
#         """
#         # Check cache for final recommendations
#         request_params = {
#             'latitude': latitude,
#             'longitude': longitude,
#             'max_distance_km': max_distance_km,
#             'limit': limit,
#             'category_filter': category_filter
#         }
        
#         if not force_refresh:
#             cached_recs = await cache.get_recommendations(user_id, request_params)
#             if cached_recs:
#                 return {
#                     **cached_recs,
#                     'cache_hit': True
#                 }
        
#         # Stage 1: Generate candidates
#         candidates = await self.generate_candidates(db, cache, user_id, force_refresh)
        
#         if not candidates:
#             return {
#                 'user_id': user_id,
#                 'recommendations': [],
#                 'computed_at': datetime.now(),
#                 'cache_hit': False
#             }
#         print(candidates)
#         # Stage 2: Rank candidates
#         context = {}
#         if latitude and longitude:
#             context['latitude'] = latitude
#             context['longitude'] = longitude
        
#         ranked = await self.rank_candidates(db, user_id, candidates, context)
        
#         # Get place data for re-ranking
#         place_ids = [place_id for place_id, _ in ranked]
#         places_result = await db.execute(
#             select(Place).where(Place.place_id.in_(place_ids))
#         )
#         places = places_result.scalars().all()
#         places_dict = {
#             p.place_id: {
#                 'place_id': p.place_id,
#                 'name': p.name,
#                 'category': p.category,
#                 'latitude': p.latitude,
#                 'longitude': p.longitude,
#                 'avg_rating': p.avg_rating,
#                 'popularity_score': p.popularity_score,
#                 'crowd_level': p.crowd_level,
#                 'created_at': p.created_at,
#                 'updated_at': p.updated_at
#             }
#             for p in places
#         }
#         print("ranked",ranked)
#         # Stage 3: Re-rank with freshness and distance
#         # user_location = (latitude, longitude) if latitude and longitude else None
        
#         # reranked = self.reranker.rerank(
#         #     ranked_recommendations=ranked,
#         #     places_data=places_dict,
#         #     user_location=user_location,
#         #     current_time=datetime.now(),
#         #     promote_diversity=True
#         # )
        
#         # # Apply filters
#         # if max_distance_km:
#         #     reranked = [
#         #         r for r in reranked
#         #         if r.get('distance_km') is None or r['distance_km'] <= max_distance_km
#         #     ]
        
#         # if category_filter:
#         #     reranked = [
#         #         r for r in reranked
#         #         if r.get('category') in category_filter
#         #     ]
        
#         # Take top N
#         #final_recommendations = ranked[:20]
#         final_recommendations = [
#               {"place_id": pid, "final_score": score}
#             for pid, score in ranked[:limit]
# ]

#         print("____________",final_recommendations)
#         # Enrich with full place data

#         enriched_recommendations = []
        
#         for rec in final_recommendations:
#             place_id = rec['place_id']
#             place = places_dict.get(place_id)
            
#             if place:
#                 # Get full place object
#                 place_obj_result = await db.execute(
#                     select(Place).where(Place.place_id == place_id)
#                 )
#                 place_obj = place_obj_result.scalar_one_or_none()
                
#                 enriched_recommendations.append({
#                     'place': {
#                         'place_id': place_obj.place_id,
#                         'name': place_obj.name,
#                         'category': place_obj.category,
#                         'city': place_obj.city,
#                         'latitude': place_obj.latitude,
#                         'longitude': place_obj.longitude,
#                         'description': place_obj.description,
#                         'tags': place_obj.tags,
#                         'avg_cost': place_obj.avg_cost,
#                         'avg_rating': place_obj.avg_rating,
#                         'crowd_level': place_obj.crowd_level,
#                         'popularity_score': place_obj.popularity_score,
#                         # 'images': place_obj.images,
#                         # 'cover_image': place_obj.cover_image,
#                         # 'distance_km': rec.get('distance_km')
#                     },
#                     'score': rec['final_score'],
#                     # 'als_score': rec.get('base_score'),
#                     # 'freshness_score': rec.get('freshness_score'),
#                     # 'distance_score': rec.get('distance_score'),
#                     # 'distance_km': rec.get('distance_km'),
#                     # 'explanation': self.reranker.explain_ranking(rec)
#                 })
        
#         result = {
#             'user_id': user_id,
#             'recommendations': enriched_recommendations,
#             'computed_at': datetime.now(),
#             'cache_hit': False
#         }
#         print(enriched_recommendations)
#         print(result)
#         #Cache the result
#         await cache.cache_recommendations(user_id, request_params, result)
        
#         return result
    


# Global instance
recommendation_service = RecommendationService()

# if __name__ == "__main__":
#     import asyncio
#     from database.connection import AsyncSessionLocal
#     from services.cache import cache as global_cache

#     async def _demo():
#         """Quick demo runner for `get_recommendations`.
#         - connects cache
#         - opens an async DB session
#         - loads models (if present)
#         - runs `get_recommendations` and prints the final output
#         """
#         await global_cache.connect()
#         # use a session from the project's async session factory
#         async with AsyncSessionLocal() as db:
#             recommendation_service.load_models()
#             # change user_id and args as needed for your environment
#             result = await recommendation_service.get_recommendations(
#                 db=db,
#                 cache=global_cache,
#                 user_id=1,
#                 limit=5,
#                 force_refresh=True
#             )
#             print("FINAL RECOMMENDATIONS (demo):", result)
#         await global_cache.close()

#     asyncio.run(_demo())