import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from geopy.distance import geodesic


class ReRanker:
    """
    Re-rank recommendations using freshness, distance, and other contextual factors
    """
    
    def __init__(
        self,
        freshness_weight: float = 0.2,
        distance_weight: float = 0.3,
        score_weight: float = 0.5,
        freshness_decay_days: int = 30,
        distance_threshold_km: float = 100.0
    ):
        """
        Initialize re-ranker
        
        Args:
            freshness_weight: Weight for freshness score
            distance_weight: Weight for distance score  
            score_weight: Weight for original ranking score
            freshness_decay_days: Days after which places get lower freshness scores
            distance_threshold_km: Distance within which places get full distance score
        """
        self.freshness_weight = freshness_weight
        self.distance_weight = distance_weight
        self.score_weight = score_weight
        self.freshness_decay_days = freshness_decay_days
        self.distance_threshold_km = distance_threshold_km
        
        # Normalize weights
        total_weight = freshness_weight + distance_weight + score_weight
        self.freshness_weight /= total_weight
        self.distance_weight /= total_weight
        self.score_weight /= total_weight
    
    def _calculate_freshness_score(
        self,
        place_created_at: datetime,
        place_updated_at: datetime = None,
        current_time: datetime = None
    ) -> float:
        """
        Calculate freshness score for a place
        
        New or recently updated places get higher scores
        Score decays over time using exponential decay
        
        Returns:
            Freshness score between 0 and 1
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Use the most recent timestamp
        reference_time = place_updated_at if place_updated_at else place_created_at
        
        if reference_time is None:
            return 0.5  # Default score for places without timestamp
        
        # Calculate days since creation/update
        days_old = (current_time - reference_time).days
        
        # Exponential decay: score = e^(-days/decay_period)
        decay_rate = 1.0 / self.freshness_decay_days
        freshness_score = np.exp(-decay_rate * days_old)
        
        return float(freshness_score)
    
    def _calculate_distance_score(
        self,
        user_location: Tuple[float, float],
        place_location: Tuple[float, float]
    ) -> Tuple[float, float]:
        """
        Calculate distance score and actual distance
        
        Closer places get higher scores
        Places within threshold get full score
        Score decays logarithmically beyond threshold
        
        Args:
            user_location: (latitude, longitude) of user
            place_location: (latitude, longitude) of place
            
        Returns:
            (distance_score, distance_km)
        """
        # Calculate geodesic distance
        distance_km = geodesic(user_location, place_location).kilometers
        
        # Calculate score
        if distance_km <= self.distance_threshold_km:
            # Full score for nearby places
            score = 1.0
        else:
            # Logarithmic decay for farther places
            # score = 1 / (1 + log(distance/threshold))
            ratio = distance_km / self.distance_threshold_km
            score = 1.0 / (1.0 + np.log(ratio))
        
        return float(score), float(distance_km)
    
    def _calculate_popularity_boost(
        self,
        popularity_score: float,
        avg_rating: float
    ) -> float:
        """
        Calculate a boost factor based on popularity and ratings
        
        This helps surface high-quality, popular places
        """
        # Normalize inputs
        norm_popularity = min(popularity_score / 100.0, 1.0)
        norm_rating = avg_rating / 5.0
        
        # Confidence factor based on review count
        # More reviews = higher confidence in rating
        #confidence = min(review_count / 100.0, 1.0)
        
        # Weighted combination
        boost = (
            0.5 * norm_popularity +
            0.5 * norm_rating 
        )
        
        return boost
    
    def _calculate_diversity_penalty(
        self,
        current_recommendations: List[int],
        place_category: str,
        place_id: int,
        category_counts: Dict[str, int],
        max_per_category: int = 5
    ) -> float:
        """
        Calculate penalty for over-representing a category
        
        Promotes diversity in recommendations
        """
        if place_category not in category_counts:
            return 1.0  # No penalty for first item in category
        
        count = category_counts[place_category]
        
        if count >= max_per_category:
            # Strong penalty
            return 0.5
        elif count >= max_per_category * 0.75:
            # Moderate penalty
            return 0.75
        else:
            # Light penalty
            return 0.9
    
    def rerank(
        self,
        ranked_recommendations: List[Tuple[int, float]],
        places_data: Dict[int, Dict],
        user_location: Tuple[float, float] = None,
        current_time: datetime = None,
        promote_diversity: bool = True,
        max_per_category: int = 5
    ) -> List[Dict]:
        """
        Re-rank recommendations using freshness, distance, and diversity
        
        Args:
            ranked_recommendations: List of (place_id, score) from LambdaRank
            places_data: Dict mapping place_id to place attributes
            user_location: (latitude, longitude) of user
            current_time: Current timestamp
            promote_diversity: Whether to promote category diversity
            max_per_category: Maximum places per category before penalty
            
        Returns:
            List of dicts with place_id, final_score, and score components
        """
        if current_time is None:
            current_time = datetime.now()
        
        reranked = []
        category_counts = {}
        
        for place_id, base_score in ranked_recommendations:
            if place_id not in places_data:
                continue
            
            place = places_data[place_id]
            
            # Calculate freshness score
            freshness_score = self._calculate_freshness_score(
                place_created_at=place.get('created_at'),
                place_updated_at=place.get('updated_at'),
                current_time=current_time
            )
            
            # Calculate distance score
            distance_score = 0.5  # Default
            distance_km = None
            
            if user_location and place.get('latitude') and place.get('longitude'):
                place_location = (place['latitude'], place['longitude'])
                distance_score, distance_km = self._calculate_distance_score(
                    user_location, place_location
                )
            
            # Calculate popularity boost
            popularity_boost = self._calculate_popularity_boost(
                popularity_score=place.get('popularity_score', 0),
                avg_rating=place.get('avg_rating', 0)
               # review_count=place.get('review_count', 0)
            )
            
            # Calculate diversity penalty
            diversity_factor = 1.0
            place_category = place.get('category', 'unknown')
            
            if promote_diversity:
                diversity_factor = self._calculate_diversity_penalty(
                    current_recommendations=[r['place_id'] for r in reranked],
                    place_category=place_category,
                    place_id=place_id,
                    category_counts=category_counts,
                    max_per_category=max_per_category
                )
            
            # Update category count
            category_counts[place_category] = category_counts.get(place_category, 0) + 1
            
            # Calculate final score
            final_score = (
                self.score_weight * base_score +
                self.freshness_weight * freshness_score +
                self.distance_weight * distance_score
            )
            
            # Apply boosts and penalties
            final_score = final_score * (1.0 + 0.2 * popularity_boost) * diversity_factor
            
            # Store result
            reranked.append({
                'place_id': place_id,
                'final_score': float(final_score),
                'base_score': float(base_score),
                'freshness_score': float(freshness_score),
                'distance_score': float(distance_score),
                'distance_km': distance_km,
                'popularity_boost': float(popularity_boost),
                'diversity_factor': float(diversity_factor),
                'category': place_category
            })
        
        # Sort by final score
        reranked.sort(key=lambda x: x['final_score'], reverse=True)
        
        return reranked
    
    def filter_by_constraints(
        self,
        recommendations: List[Dict],
        max_distance_km: float = None,
        min_rating: float = None,
        budget_range: Tuple[float, float] = None,
        categories: List[str] = None,
        crowd_levels: List[str] = None
    ) -> List[Dict]:
        """
        Filter recommendations by user constraints
        
        Args:
            recommendations: List of recommendation dicts
            max_distance_km: Maximum distance filter
            min_rating: Minimum rating filter
            budget_range: (min_cost, max_cost) filter
            categories: List of allowed categories
            crowd_levels: List of allowed crowd levels
            
        Returns:
            Filtered list of recommendations
        """
        filtered = recommendations.copy()
        
        # Distance filter
        if max_distance_km is not None:
            filtered = [
                r for r in filtered
                if r.get('distance_km') is None or r['distance_km'] <= max_distance_km
            ]
        
        # Additional filters would be applied here based on places_data
        # These require access to full place information
        
        return filtered
    
    def explain_ranking(self, recommendation: Dict) -> str:
        """
        Generate human-readable explanation for a recommendation's ranking
        
        Args:
            recommendation: Single recommendation dict with scores
            
        Returns:
            Explanation string
        """
        explanations = []
        
        # Distance explanation
        if recommendation.get('distance_km') is not None:
            dist = recommendation['distance_km']
            if dist < 1:
                explanations.append(f"Very close to you ({dist:.1f} km)")
            elif dist < 10:
                explanations.append(f"Nearby ({dist:.1f} km)")
            else:
                explanations.append(f"Within {dist:.0f} km")
        
        # Freshness explanation
        freshness = recommendation.get('freshness_score', 0)
        if freshness > 0.8:
            explanations.append("Recently added or updated")
        
        # Popularity explanation
        popularity = recommendation.get('popularity_boost', 0)
        if popularity > 0.7:
            explanations.append("Highly rated and popular")
        elif popularity > 0.5:
            explanations.append("Well-rated")
        
        # Base score explanation
        base_score = recommendation.get('base_score', 0)
        if base_score > 0.8:
            explanations.append("Matches your preferences well")
        
        return " • ".join(explanations) if explanations else "Recommended for you"