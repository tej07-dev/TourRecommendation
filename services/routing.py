import httpx
import asyncio
import logging
from typing import List, Dict, Tuple, Optional, Any
from itertools import permutations
from functools import wraps

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def retry_with_backoff(retries=3, initial_delay=1):
    """Decorator for exponential backoff on API calls."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (httpx.HTTPError, asyncio.TimeoutError) as e:
                    if i == retries - 1:
                        logger.error(f"Final retry failed: {e}")
                        raise
                    logger.warning(f"API call failed (attempt {i+1}), retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    delay *= 2
            return None
        return wrapper
    return decorator

class OSMRoutingService:
    """
    Production-ready Road-accurate routing service using OSRM.
    Includes support for identifying traffic signals and road metadata.
    """

    def __init__(self, base_url: str = "http://router.project-osrm.org"):
        self.base_url = base_url
        self.profile = "driving"
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=30.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
        )

    async def close(self):
        """Clean up the client connection pool."""
        await self.client.aclose()

    @retry_with_backoff(retries=3)
    async def get_route(
        self,
        waypoints: List[Tuple[float, float]],
        profile: str = "driving",
        include_metadata: bool = True
    ) -> Optional[Dict]:
        """
        Fetches route with optional metadata like traffic signals.
        """
        if len(waypoints) < 2:
            return None

        coordinates = ";".join([f"{lon},{lat}" for lon, lat in waypoints])
        url = f"{self.base_url}/route/v1/{profile}/{coordinates}"
        
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",
            "annotations": "nodes,duration,distance" if include_metadata else "true"
        }

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == "Ok" and include_metadata:
            # We can process the 'nodes' here if we have an external OSM database 
            # to check which node IDs are actually 'highway=traffic_signals'
            pass

        return data if data.get("code") == "Ok" else None

    def count_traffic_signals_in_steps(self, route_data: Dict) -> int:
        """
        Analyzes the 'steps' in the route data to find traffic signals.
        Note: OSRM identifies these in the 'intersections' array of each step.
        """
        signal_count = 0
        try:
            for route in route_data.get("routes", []):
                for leg in route.get("legs", []):
                    for step in leg.get("steps", []):
                        for intersection in step.get("intersections", []):
                            # 'classes' may contain 'traffic_light' depending on OSRM profile
                            classes = intersection.get("classes", [])
                            if "traffic_light" in classes:
                                signal_count += 1
        except Exception as e:
            logger.error(f"Error parsing signals: {e}")
        
        return signal_count

    @retry_with_backoff(retries=3)
    async def get_distance_matrix(
        self,
        waypoints: List[Tuple[float, float]],
        profile: str = "driving"
    ) -> Optional[Dict]:
        coordinates = ";".join([f"{lon},{lat}" for lon, lat in waypoints])
        url = f"{self.base_url}/table/v1/{profile}/{coordinates}"

        params = {
            "annotations": "distance,duration",
            "radiuses": ";".join(["1000"] * len(waypoints))
        }

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return data if data.get("code") == "Ok" else None

    async def optimize_route(
        self,
        start_point: Tuple[float, float],
        end_point: Tuple[float, float],
        intermediate_points: List[Tuple[float, float]],
        places_data: List[Dict],
        profile: str = "driving"
    ) -> Optional[List[int]]:
        if not intermediate_points:
            return []

        all_points = [start_point] + intermediate_points + [end_point]
        matrix_data = await self.get_distance_matrix(all_points, profile)
        
        if not matrix_data or "distances" not in matrix_data:
            return list(range(len(intermediate_points)))

        distance_matrix = matrix_data["distances"]
        duration_matrix = matrix_data["durations"]

        for i in range(len(distance_matrix)):
            for j in range(len(distance_matrix[i])):
                if distance_matrix[i][j] is None:
                    distance_matrix[i][j] = 999999.0 
                if duration_matrix[i][j] is None:
                    duration_matrix[i][j] = 999999.0

        n = len(intermediate_points)
        if n <= 7:
            return self._optimize_brute_force(distance_matrix, duration_matrix, places_data)
        else:
            return self._optimize_greedy(distance_matrix, duration_matrix, places_data)

    def _calculate_score(self, order, distance_matrix, duration_matrix, places_data) -> float:
        total_dist = 0
        total_dur = 0
        
        prev = 0
        for idx in order:
            matrix_idx = idx + 1
            total_dist += distance_matrix[prev][matrix_idx]
            total_dur += duration_matrix[prev][matrix_idx]
            prev = matrix_idx
            
        end_idx = len(distance_matrix) - 1
        total_dist += distance_matrix[prev][end_idx]
        total_dur += duration_matrix[prev][end_idx]

            # Popularity penalty
#         popularity_penalty = 0
#         for i, idx in enumerate(order):
#             popularity = places_data[idx].get("popularity_score", 50) / 100.0
#             position_weight = (i + 1) / len(order)
#             popularity_penalty += position_weight * (1 - popularity)

#         # Normalize distance (meters → km)
#         total_distance_km = total_distance / 1000.0
#         total_duration_min = total_duration / 60.0

#         score = (
#             settings.ROUTE_DISTANCE_WEIGHT * total_distance_km +
#             settings.ROUTE_DURATION_WEIGHT * total_duration_min +
#             settings.ROUTE_POPULARITY_WEIGHT * popularity_penalty
#         )

#         return score


        # The 'duration_matrix' from OSRM already includes predicted delays 
        # caused by traffic lights based on historical OSM data.
        return (total_dist * 0.0005) + (total_dur * 0.01)

    def _optimize_brute_force(self, dist_m, dur_m, places) -> List[int]:
        n = len(places)
        best_score = float("inf")
        best_order = list(range(n))

        for perm in permutations(range(n)):
            score = self._calculate_score(perm, dist_m, dur_m, places)
            if score < best_score:
                best_score = score
                best_order = list(perm)
        return best_order

    def _optimize_greedy(self, dist_m, dur_m, places) -> List[int]:
        n = len(places)
        unvisited = set(range(n))
        order = []
        curr = 0

        while unvisited:
            best_idx = -1
            min_eff_dist = float("inf")
            for idx in unvisited:
                m_idx = idx + 1
                dist = dist_m[curr][m_idx]
                pop = places[idx].get("popularity_score", 50) / 100.0
                eff = dist * (1 - 0.2 * pop)
                
                if eff < min_eff_dist:
                    min_eff_dist = eff
                    best_idx = idx
            
            order.append(best_idx)
            unvisited.remove(best_idx)
            curr = best_idx + 1
        
        return self._two_opt(order, dist_m, dur_m, places)

    def _two_opt(self, order, dist_m, dur_m, places):
        improved = True
        while improved:
            improved = False
            for i in range(len(order) - 1):
                for j in range(i + 2, len(order)):
                    new_order = order[:i+1] + order[i+1:j+1][::-1] + order[j+1:]
                    if self._calculate_score(new_order, dist_m, dur_m, places) < \
                       self._calculate_score(order, dist_m, dur_m, places):
                        order = new_order
                        improved = True
                        break
                if improved: break
        return order
    
    def extract_route_segments(self, route_data: Dict, waypoint_names: List[str]) -> List[Any]:
        """
        Helper to format OSRM legs into individual route segments.
        This matches the logic expected by your /routes endpoint.
        """
        routes = route_data.get("routes", [])
        if not routes:
            return []

        legs = routes[0].get("legs", [])
        segments = []

        for i, leg in enumerate(legs):
            # Intersection-based traffic light count for this specific leg
            signal_count = 0
            for step in leg.get("steps", []):
                for intersection in step.get("intersections", []):
                    if "traffic_light" in intersection.get("classes", []):
                        signal_count += 1
                        
        full_geometry = []

        for step in leg.get("steps", []):
            step_geom = step.get("geometry", {}).get("coordinates", [])
            full_geometry.extend(step_geom)

        segments.append({
            "from_place": waypoint_names[i],
            "to_place": waypoint_names[i+1],
            "distance_km": leg.get("distance", 0) / 1000.0,
            "duration_minutes": leg.get("duration", 0) / 60.0,
            "traffic_signals": signal_count,
            "geometry": full_geometry
        })

                    
        return segments

routing_service=OSMRoutingService()    
# import httpx
# from typing import List, Dict, Tuple, Optional
# import numpy as np
# from itertools import permutations
# from config.settings import get_settings
# from schema.api_response_schema import RouteSegment

# settings = get_settings()


# class OSMRoutingService:
#     """
#     Road-accurate routing service using OSRM
#     Uses OSRM Distance Matrix API for optimization
#     """

#     def __init__(self):
#         self.base_url = "http://router.project-osrm.org"
#         self.profile = "driving"

#     # -------------------------------------------------------
#     # ROUTE API (FINAL PATH DRAWING)
#     # -------------------------------------------------------
#     async def get_route(
#         self,
#         waypoints: List[Tuple[float, float]],
#         profile: str = "driving"
#     ) -> Optional[Dict]:

#         if len(waypoints) < 2:
#             return None

#         coordinates = ";".join([f"{lon},{lat}" for lon, lat in waypoints])

#         url = f"{self.base_url}/route/v1/{profile}/{coordinates}"

#         params = {
#             "overview": "full",
#             "geometries": "geojson",
#             "steps": "true"
#         }

#         async with httpx.AsyncClient() as client:
#             response = await client.get(url, params=params, timeout=30.0)
#             response.raise_for_status()
#             data = response.json()

#         if data.get("code") != "Ok":
#             return None

#         return data

#     # -------------------------------------------------------
#     # DISTANCE MATRIX (KEY UPGRADE)
#     # -------------------------------------------------------
#     async def get_distance_matrix(
#         self,
#         waypoints: List[Tuple[float, float]],
#         profile: str = "driving"
#     ) -> Optional[Dict]:

#         coordinates = ";".join([f"{lon},{lat}" for lon, lat in waypoints])
#         url = f"{self.base_url}/table/v1/{profile}/{coordinates}"

#         params = {
#             "annotations": "distance,duration"
#         }

#         async with httpx.AsyncClient() as client:
#             response = await client.get(url, params=params, timeout=30.0)
#             response.raise_for_status()
#             data = response.json()

#         if data.get("code") != "Ok":
#             return None

#         return data

#     # -------------------------------------------------------
#     # OPTIMIZATION ENTRY
#     # -------------------------------------------------------
#     async def optimize_route(
#         self,
#         start_point: Tuple[float, float],
#         end_point: Tuple[float, float],
#         intermediate_points: List[Tuple[float, float]],
#         places_data: List[Dict],
#         profile: str = "driving"
#     ) -> Optional[List[int]]:

#         if not intermediate_points:
#             return []

#         # Build full waypoint list: start + intermediates + end
#         all_points = [start_point] + intermediate_points + [end_point]

#         matrix_data = await self.get_distance_matrix(all_points, profile)
#         if not matrix_data:
#             return None

#         distance_matrix = matrix_data["distances"]
#         duration_matrix = matrix_data["durations"]

#         n = len(intermediate_points)

#         if n <= 6:
#             return self._optimize_brute_force(
#                 distance_matrix,
#                 duration_matrix,
#                 places_data
#             )
#         else:
#             return self._optimize_greedy(
#                 distance_matrix,
#                 duration_matrix,
#                 places_data
#             )

#     # -------------------------------------------------------
#     # BRUTE FORCE (ROAD ACCURATE)
#     # -------------------------------------------------------
#     def _optimize_brute_force(
#         self,
#         distance_matrix: List[List[float]],
#         duration_matrix: List[List[float]],
#         places_data: List[Dict]
#     ) -> List[int]:

#         n = len(places_data)
#         best_score = float("inf")
#         best_order = list(range(n))

#         for perm in permutations(range(n)):
#             score = self._calculate_score(
#                 perm,
#                 distance_matrix,
#                 duration_matrix,
#                 places_data
#             )

#             if score < best_score:
#                 best_score = score
#                 best_order = list(perm)

#         return best_order

#     # -------------------------------------------------------
#     # GREEDY + 2-OPT (ROAD ACCURATE)
#     # -------------------------------------------------------
#     def _optimize_greedy(
#         self,
#         distance_matrix,
#         duration_matrix,
#         places_data
#     ) -> List[int]:

#         n = len(places_data)
#         unvisited = set(range(n))
#         order = []

#         current_index = 0  # start node index in matrix

#         while unvisited:
#             best_idx = None
#             best_score = float("inf")

#             for idx in unvisited:
#                 matrix_idx = idx + 1  # shift because start at 0

#                 road_distance = distance_matrix[current_index][matrix_idx]
#                 popularity = places_data[idx].get("popularity_score", 50) / 100.0

#                 effective_score = road_distance * (1 - 0.3 * popularity)

#                 if effective_score < best_score:
#                     best_score = effective_score
#                     best_idx = idx

#             order.append(best_idx)
#             unvisited.remove(best_idx)
#             current_index = best_idx + 1

#         # Apply 2-opt improvement
#         order = self._two_opt(order, distance_matrix, duration_matrix, places_data)

#         return order

#     # -------------------------------------------------------
#     # 2-OPT
#     # -------------------------------------------------------
#     def _two_opt(self, order, distance_matrix, duration_matrix, places_data):

#         improved = True
#         while improved:
#             improved = False

#             for i in range(len(order) - 1):
#                 for j in range(i + 2, len(order)):

#                     new_order = (
#                         order[:i + 1]
#                         + order[i + 1:j + 1][::-1]
#                         + order[j + 1:]
#                     )

#                     current_score = self._calculate_score(
#                         order, distance_matrix, duration_matrix, places_data
#                     )
#                     new_score = self._calculate_score(
#                         new_order, distance_matrix, duration_matrix, places_data
#                     )

#                     if new_score < current_score:
#                         order = new_order
#                         improved = True
#                         break

#                 if improved:
#                     break

#         return order

#     # -------------------------------------------------------
#     # ROAD-ACCURATE SCORE
#     # -------------------------------------------------------
#     def _calculate_score(
#         self,
#         order,
#         distance_matrix,
#         duration_matrix,
#         places_data
#     ) -> float:

#         total_distance = 0
#         total_duration = 0

#         # Start -> first
#         prev = 0

#         for idx in order:
#             matrix_idx = idx + 1
#             total_distance += distance_matrix[prev][matrix_idx]
#             total_duration += duration_matrix[prev][matrix_idx]
#             prev = matrix_idx

#         # Last -> end
#         end_index = len(distance_matrix) - 1
#         total_distance += distance_matrix[prev][end_index]
#         total_duration += duration_matrix[prev][end_index]

#         # Popularity penalty
#         popularity_penalty = 0
#         for i, idx in enumerate(order):
#             popularity = places_data[idx].get("popularity_score", 50) / 100.0
#             position_weight = (i + 1) / len(order)
#             popularity_penalty += position_weight * (1 - popularity)

#         # Normalize distance (meters → km)
#         total_distance_km = total_distance / 1000.0
#         total_duration_min = total_duration / 60.0

#         score = (
#             settings.ROUTE_DISTANCE_WEIGHT * total_distance_km +
#             settings.ROUTE_DURATION_WEIGHT * total_duration_min +
#             settings.ROUTE_POPULARITY_WEIGHT * popularity_penalty
#         )

#         return score

# # import httpx
# # from typing import List, Dict, Tuple, Optional
# # import numpy as np
# # from itertools import permutations
# # from config.settings import get_settings
# # from schema.api_response_schema import RouteWaypoint, RouteSegment
# # from geopy.distance import geodesic

# # settings = get_settings()


# # class OSMRoutingService:
# #     """Service for route planning using OpenStreetMap"""
    
# #     def __init__(self):
# #         # Using OSRM (Open Source Routing Machine) demo server
# #         # In production, you should host your own OSRM instance
# #         self.base_url = "http://router.project-osm.org/route/v1"
# #         self.profile = "driving"  # driving, cycling, walking
    
# #     async def get_route(
# #         self,
# #         waypoints: List[Tuple[float, float]],
# #         profile: str = "driving"
# #     ) -> Optional[Dict]:
# #         """
# #         Get route between waypoints
        
# #         Args:
# #             waypoints: List of (longitude, latitude) tuples
# #             profile: Routing profile (driving, cycling, walking)
            
# #         Returns:
# #             Route data dict or None
# #         """
# #         if len(waypoints) < 2:
# #             return None
        
# #         # Format waypoints for OSRM
# #         # OSRM expects lon,lat format
# #         coordinates = ";".join([f"{lon},{lat}" for lon, lat in waypoints])
        
# #         url = f"{self.base_url}/{profile}/{coordinates}"
        
# #         params = {
# #             "overview": "full",
# #             "geometries": "geojson",
# #             "steps": "true",
# #             "annotations": "true"
# #         }
        
# #         try:
# #             async with httpx.AsyncClient() as client:
# #                 response = await client.get(
# #                     url,
# #                     params=params,
# #                     timeout=30.0
# #                 )
# #                 response.raise_for_status()
# #                 data = response.json()
            
# #             if data.get("code") != "Ok":
# #                 print(f"OSRM error: {data.get('message')}")
# #                 return None
            
# #             return data
            
# #         except httpx.HTTPError as e:
# #             print(f"OSRM API error: {e}")
# #             return None
# #         except Exception as e:
# #             print(f"Error fetching route: {e}")
# #             return None
    
# #     async def optimize_route(
# #         self,
# #         start_point: Tuple[float, float],
# #         end_point: Tuple[float, float],
# #         intermediate_points: List[Tuple[float, float]],
# #         places_data: List[Dict],
# #         profile: str = "driving"
# #     ) -> Optional[List[int]]:
# #         """
# #         Optimize waypoint order for tourist experience
        
# #         Considers:
# #         - Distance minimization
# #         - Place popularity (visit popular places earlier)
# #         - Scenic value
# #         - Logical flow (no excessive backtracking)
        
# #         Args:
# #             start_point: Starting location (lon, lat)
# #             end_point: Ending location (lon, lat)
# #             intermediate_points: List of intermediate waypoints (lon, lat)
# #             places_data: List of place data dicts with popularity_score
# #             profile: Routing profile
            
# #         Returns:
# #             Optimized order of intermediate point indices
# #         """
# #         n = len(intermediate_points)
        
# #         if n == 0:
# #             return []
        
# #         if n <= 6:
# #             # For small number of points, try all permutations
# #             return await self._optimize_brute_force(
# #                 start_point, end_point, intermediate_points, places_data
# #             )
# #         else:
# #             # For larger sets, use greedy + local optimization
# #             return await self._optimize_greedy(
# #                 start_point, end_point, intermediate_points, places_data
# #             )
    
# #     async def _optimize_brute_force(
# #         self,
# #         start: Tuple[float, float],
# #         end: Tuple[float, float],
# #         points: List[Tuple[float, float]],
# #         places_data: List[Dict]
# #     ) -> List[int]:
# #         """Brute force optimization for small sets"""
# #         n = len(points)
# #         best_order = list(range(n))
# #         best_score = float('inf')
        
# #         for perm in permutations(range(n)):
# #             score = self._calculate_route_score(
# #                 start, end, [points[i] for i in perm], 
# #                 [places_data[i] for i in perm]
# #             )
            
# #             if score < best_score:
# #                 best_score = score
# #                 best_order = list(perm)
        
# #         return best_order
    
# #     async def _optimize_greedy(
# #         self,
# #         start: Tuple[float, float],
# #         end: Tuple[float, float],
# #         points: List[Tuple[float, float]],
# #         places_data: List[Dict]
# #     ) -> List[int]:
# #         """Greedy optimization with 2-opt local search"""
# #         n = len(points)
        
# #         # Start with nearest neighbor heuristic
# #         order = self._nearest_neighbor(start, end, points, places_data)
        
# #         # Apply 2-opt improvements
# #         improved = True
# #         iterations = 0
# #         max_iterations = 100
        
# #         while improved and iterations < max_iterations:
# #             improved = False
# #             iterations += 1
            
# #             for i in range(n - 1):
# #                 for j in range(i + 2, n):
# #                     # Try reversing segment [i+1, j]
# #                     new_order = order[:i+1] + order[i+1:j+1][::-1] + order[j+1:]
                    
# #                     current_score = self._calculate_route_score(
# #                         start, end,
# #                         [points[idx] for idx in order],
# #                         [places_data[idx] for idx in order]
# #                     )
                    
# #                     new_score = self._calculate_route_score(
# #                         start, end,
# #                         [points[idx] for idx in new_order],
# #                         [places_data[idx] for idx in new_order]
# #                     )
                    
# #                     if new_score < current_score:
# #                         order = new_order
# #                         improved = True
# #                         break
                
# #                 if improved:
# #                     break
        
# #         return order
    
# #     def _nearest_neighbor(
# #         self,
# #         start: Tuple[float, float],
# #         end: Tuple[float, float],
# #         points: List[Tuple[float, float]],
# #         places_data: List[Dict]
# #     ) -> List[int]:
# #         """Nearest neighbor heuristic with popularity bias"""
# #         n = len(points)
# #         unvisited = set(range(n))
# #         order = []
# #         current = start
        
# #         while unvisited:
# #             # Find nearest unvisited point with popularity bias
# #             best_idx = None
# #             best_score = float('inf')
            
# #             for idx in unvisited:
# #                 point = points[idx]
# #                 distance = geodesic(
# #                     (current[1], current[0]),
# #                     (point[1], point[0])
# #                 ).kilometers
                
# #                 # Bias towards popular places (reduce effective distance)
# #                 popularity = places_data[idx].get('popularity_score', 50) / 100.0
# #                 effective_distance = distance * (1.0 - 0.3 * popularity)
                
# #                 if effective_distance < best_score:
# #                     best_score = effective_distance
# #                     best_idx = idx
            
# #             order.append(best_idx)
# #             unvisited.remove(best_idx)
# #             current = points[best_idx]
        
# #         return order
    
# #     def _calculate_route_score(
# #         self,
# #         start: Tuple[float, float],
# #         end: Tuple[float, float],
# #         ordered_points: List[Tuple[float, float]],
# #         ordered_places: List[Dict]
# #     ) -> float:
# #         """
# #         Calculate route quality score
        
# #         Lower is better
# #         Considers: total distance, backtracking, popularity sequence
# #         """
# #         # Calculate total distance
# #         total_distance = 0
# #         current = start
        
# #         for point in ordered_points:
# #             distance = geodesic(
# #                 (current[1], current[0]),
# #                 (point[1], point[0])
# #             ).kilometers
# #             total_distance += distance
# #             current = point
        
# #         # Add distance to end
# #         total_distance += geodesic(
# #             (current[1], current[0]),
# #             (end[1], end[0])
# #         ).kilometers
        
# #         # Calculate backtracking penalty
# #         backtracking_penalty = self._calculate_backtracking(
# #             start, end, ordered_points
# #         )
        
# #         # Calculate popularity sequence penalty
# #         # Prefer visiting popular places earlier
# #         popularity_penalty = 0
# #         for i, place in enumerate(ordered_places):
# #             popularity = place.get('popularity_score', 50) / 100.0
# #             # Penalty increases if popular places are later in route
# #             position_weight = (i + 1) / len(ordered_places)
# #             popularity_penalty += position_weight * (1.0 - popularity)
        
# #         # Weighted combination
# #         score = (
# #             settings.ROUTE_DISTANCE_WEIGHT * total_distance +
# #             settings.ROUTE_SCENIC_WEIGHT * backtracking_penalty * 10 +
# #             settings.ROUTE_POPULARITY_WEIGHT * popularity_penalty * 50
# #         )
        
# #         return score
    
# #     def _calculate_backtracking(
# #         self,
# #         start: Tuple[float, float],
# #         end: Tuple[float, float],
# #         points: List[Tuple[float, float]]
# #     ) -> float:
# #         """Calculate backtracking penalty"""
# #         if len(points) < 2:
# #             return 0
        
# #         # Calculate direct distance from start to end
# #         direct_distance = geodesic(
# #             (start[1], start[0]),
# #             (end[1], end[0])
# #         ).kilometers
        
# #         # Calculate bearing changes
# #         total_bearing_change = 0
# #         prev_bearing = self._calculate_bearing(start, points[0])
        
# #         for i in range(len(points) - 1):
# #             bearing = self._calculate_bearing(points[i], points[i+1])
# #             bearing_change = abs(bearing - prev_bearing)
            
# #             # Normalize to 0-180
# #             if bearing_change > 180:
# #                 bearing_change = 360 - bearing_change
            
# #             total_bearing_change += bearing_change
# #             prev_bearing = bearing
        
# #         # More bearing changes = more backtracking
# #         return total_bearing_change / max(len(points), 1)
    
# #     def _calculate_bearing(
# #         self,
# #         point1: Tuple[float, float],
# #         point2: Tuple[float, float]
# #     ) -> float:
# #         """Calculate bearing between two points"""
# #         lon1, lat1 = np.radians(point1[0]), np.radians(point1[1])
# #         lon2, lat2 = np.radians(point2[0]), np.radians(point2[1])
        
# #         dlon = lon2 - lon1
        
# #         x = np.sin(dlon) * np.cos(lat2)
# #         y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
        
# #         bearing = np.arctan2(x, y)
# #         bearing = np.degrees(bearing)
# #         bearing = (bearing + 360) % 360
        
# #         return bearing
    
# #     def parse_route_geometry(self, route_data: Dict) -> List[List[float]]:
# #         """
# #         Extract route geometry from OSRM response
        
# #         Args:
# #             route_data: OSRM route response
            
# #         Returns:
# #             List of [lon, lat] coordinates
# #         """
# #         routes = route_data.get("routes", [])
# #         if not routes:
# #             return []
        
# #         geometry = routes[0].get("geometry", {})
# #         coordinates = geometry.get("coordinates", [])
        
# #         return coordinates
    
# #     def extract_route_segments(
# #         self,
# #         route_data: Dict,
# #         waypoint_names: List[str]
# #     ) -> List[RouteSegment]:
# #         """
# #         Extract route segments between waypoints
        
# #         Args:
# #             route_data: OSRM route response
# #             waypoint_names: List of place names for waypoints
            
# #         Returns:
# #             List of RouteSegment objects
# #         """
# #         routes = route_data.get("routes", [])
# #         if not routes:
# #             return []
        
# #         route = routes[0]
# #         legs = route.get("legs", [])
        
# #         segments = []
        
# #         for i, leg in enumerate(legs):
# #             from_name = waypoint_names[i] if i < len(waypoint_names) else "Start"
# #             to_name = waypoint_names[i+1] if i+1 < len(waypoint_names) else "End"
            
# #             distance_km = leg.get("distance", 0) / 1000.0  # Convert meters to km
# #             duration_min = leg.get("duration", 0) / 60.0  # Convert seconds to minutes
            
# #             # Extract geometry for this leg
# #             steps = leg.get("steps", [])
# #             geometry = []
# #             for step in steps:
# #                 step_geom = step.get("geometry", {}).get("coordinates", [])
# #                 geometry.extend(step_geom)
            
# #             segment = RouteSegment(
# #                 from_place=from_name,
# #                 to_place=to_name,
# #                 distance_km=distance_km,
# #                 duration_minutes=duration_min,
# #                 geometry=geometry
# #             )
            
# #             segments.append(segment)
        
# #         return segments


# # # Global instance
# # routing_service = OSMRoutingService()