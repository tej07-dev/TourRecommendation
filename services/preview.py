import httpx
from typing import List, Dict, Optional
from datetime import datetime
from config.settings import get_settings
from schema.api_response_schema import YouTubeVideo

settings = get_settings()


class YouTubeService:
    """Service for fetching YouTube videos for places"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.YOUTUBE_API_KEY
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.max_results = settings.YOUTUBE_MAX_RESULTS
    
    async def search_place_videos(
        self,
        place_name: str,
        city: str = None,
        latitude: float = None,
        longitude: float = None,
        max_results: int = None
    ) -> List[YouTubeVideo]:
        """
        Search for videos related to a place
        
        Args:
            place_name: Name of the place
            city: City name for better search context
            latitude: Optional latitude for location-based search
            longitude: Optional longitude for location-based search
            max_results: Number of videos to return
            
        Returns:
            List of YouTubeVideo objects
        """
        if max_results is None:
            max_results = self.max_results
        
        # Build search query
        query_parts = [place_name]
        if city:
            query_parts.append(city)
        query_parts.extend(["tourism", "travel", "visit"])
        
        query = " ".join(query_parts)
        
        # Build API request parameters
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": "relevance",
            "videoDuration": "medium",  # Filter out very short videos
            "key": self.api_key
        }
        
        # Add location parameters if available
        if latitude and longitude:
            params["location"] = f"{latitude},{longitude}"
            params["locationRadius"] = f"{settings.YOUTUBE_SEARCH_RADIUS}km"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            videos = []
            video_ids = []
            
            # Extract video IDs
            for item in data.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                if video_id:
                    video_ids.append(video_id)
            
            # Get detailed video information
            if video_ids:
                videos = await self._get_video_details(video_ids)
            
            return videos
            
        except httpx.HTTPError as e:
            print(f"YouTube API error: {e}")
            return []
        except Exception as e:
            print(f"Error fetching YouTube videos: {e}")
            return []
    
    async def _get_video_details(self, video_ids: List[str]) -> List[YouTubeVideo]:
        """
        Get detailed information for videos
        
        Args:
            video_ids: List of YouTube video IDs
            
        Returns:
            List of YouTubeVideo objects with details
        """
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(video_ids),
            "key": self.api_key
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/videos",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            videos = []
            
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                statistics = item.get("statistics", {})
                content_details = item.get("contentDetails", {})
                
                video = YouTubeVideo(
                    video_id=item.get("id"),
                    title=snippet.get("title", ""),
                    description=snippet.get("description", ""),
                    thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                    channel_title=snippet.get("channelTitle", ""),
                    published_at=datetime.fromisoformat(
                        snippet.get("publishedAt", "").replace("Z", "+00:00")
                    ),
                    view_count=int(statistics.get("viewCount", 0)),
                    duration=content_details.get("duration", "")
                )
                
                videos.append(video)
            
            return videos
            
        except Exception as e:
            print(f"Error fetching video details: {e}")
            return []
    
    def _parse_duration(self, duration: str) -> int:
        """
        Parse ISO 8601 duration to seconds
        
        Args:
            duration: Duration string like "PT15M33S"
            
        Returns:
            Duration in seconds
        """
        import re
        
        pattern = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
        match = pattern.match(duration)
        
        if not match:
            return 0
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return hours * 3600 + minutes * 60 + seconds
    
    async def get_trending_travel_videos(
        self,
        region_code: str = "US",
        max_results: int = 10
    ) -> List[YouTubeVideo]:
        """
        Get trending travel videos
        
        Args:
            region_code: ISO 3166-1 alpha-2 country code
            max_results: Number of videos to return
            
        Returns:
            List of trending YouTubeVideo objects
        """
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": region_code,
            "videoCategoryId": "19",  # Travel & Events category
            "maxResults": max_results,
            "key": self.api_key
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/videos",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            video_ids = [item.get("id") for item in data.get("items", [])]
            
            if video_ids:
                return await self._get_video_details(video_ids)
            
            return []
            
        except Exception as e:
            print(f"Error fetching trending videos: {e}")
            return []


# Global instance
youtube_service = YouTubeService()