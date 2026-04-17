import httpx
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from config.settings import get_settings
from schema.api_response_schema import WeatherCondition, WeatherForecast, WeatherAlert

settings = get_settings()


class WeatherService:
    """Service for fetching weather data and alerts"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.OPENWEATHER_API_KEY
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.units = settings.OPENWEATHER_UNITS
    
    async def get_current_weather(
        self,
        latitude: float,
        longitude: float
    ) -> Optional[WeatherCondition]:
        """
        Get current weather conditions
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            
        Returns:
            WeatherCondition object or None
        """
        params = {
            "lat": latitude,
            "lon": longitude,
            "units": self.units,
            "appid": self.api_key
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/weather",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            main = data.get("main", {})
            weather = data.get("weather", [{}])[0]
            wind = data.get("wind", {})
            
            return WeatherCondition(
                temperature=main.get("temp", 0),
                feels_like=main.get("feels_like", 0),
                humidity=main.get("humidity", 0),
                description=weather.get("description", ""),
                icon=weather.get("icon", ""),
                wind_speed=wind.get("speed", 0)
            )
            
        except httpx.HTTPError as e:
            print(f"OpenWeather API error: {e}")
            return None
        except Exception as e:
            print(f"Error fetching current weather: {e}")
            return None
    
    async def get_forecast(
        self,
        latitude: float,
        longitude: float,
        days: int = 7
    ) -> List[WeatherForecast]:
        """
        Get weather forecast
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            days: Number of days to forecast (up to 7)
            
        Returns:
            List of WeatherForecast objects
        """
        # Use One Call API for forecast
        params = {
            "lat": latitude,
            "lon": longitude,
            "units": self.units,
            "exclude": "minutely,hourly",
            "appid": self.api_key
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/onecall",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            forecasts = []
            daily_data = data.get("daily", [])[:days]
            
            for day in daily_data:
                forecast = WeatherForecast(
                    date=datetime.fromtimestamp(day.get("dt", 0)),
                    temperature_max=day.get("temp", {}).get("max", 0),
                    temperature_min=day.get("temp", {}).get("min", 0),
                    description=day.get("weather", [{}])[0].get("description", ""),
                    icon=day.get("weather", [{}])[0].get("icon", ""),
                    precipitation_probability=day.get("pop", 0) * 100
                )
                forecasts.append(forecast)
            
            return forecasts
            
        except httpx.HTTPError as e:
            print(f"OpenWeather API error: {e}")
            return []
        except Exception as e:
            print(f"Error fetching forecast: {e}")
            return []
    
    async def get_weather_alerts(
        self,
        latitude: float,
        longitude: float
    ) -> List[WeatherAlert]:
        """
        Get weather alerts for location
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            
        Returns:
            List of WeatherAlert objects
        """
        # Use One Call API which includes alerts
        params = {
            "lat": latitude,
            "lon": longitude,
            "units": self.units,
            "exclude": "minutely,hourly,daily",
            "appid": self.api_key
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/onecall",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            alerts = []
            alerts_data = data.get("alerts", [])
            
            for alert_data in alerts_data:
                # Filter by alert types we care about
                event = alert_data.get("event", "")
                
                # Determine severity
                severity = self._determine_severity(alert_data)
                
                # Only include important alerts
                if severity in settings.WEATHER_ALERT_TYPES:
                    alert = WeatherAlert(
                        event=event,
                        severity=severity,
                        description=alert_data.get("description", ""),
                        start_time=datetime.fromtimestamp(alert_data.get("start", 0)),
                        end_time=datetime.fromtimestamp(alert_data.get("end", 0))
                    )
                    alerts.append(alert)
            
            return alerts
            
        except httpx.HTTPError as e:
            print(f"OpenWeather API error: {e}")
            return []
        except Exception as e:
            print(f"Error fetching weather alerts: {e}")
            return []
    
    def _determine_severity(self, alert_data: Dict) -> str:
        """
        Determine alert severity from alert data
        
        Args:
            alert_data: Alert data from API
            
        Returns:
            Severity level: 'warning', 'watch', or 'advisory'
        """
        event = alert_data.get("event", "").lower()
        description = alert_data.get("description", "").lower()
        
        # Keywords for different severity levels
        warning_keywords = ["warning", "severe", "extreme", "dangerous"]
        watch_keywords = ["watch", "possible", "potential"]
        
        for keyword in warning_keywords:
            if keyword in event or keyword in description:
                return "warning"
        
        for keyword in watch_keywords:
            if keyword in event or keyword in description:
                return "watch"
        
        return "advisory"
    
    async def get_complete_weather_data(
        self,
        latitude: float,
        longitude: float,
        include_forecast: bool = True
    ) -> Dict:
        """
        Get complete weather data including current conditions, forecast, and alerts
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            include_forecast: Whether to include forecast data
            
        Returns:
            Dict with current, forecast (optional), and alerts
        """
        # Use One Call API for efficiency
        params = {
            "lat": latitude,
            "lon": longitude,
            "units": self.units,
            "exclude": "minutely,hourly" if not include_forecast else "minutely",
            "appid": self.api_key
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/onecall",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            result = {}
            
            # Current weather
            current = data.get("current", {})
            weather = current.get("weather", [{}])[0]
            
            result["current"] = WeatherCondition(
                temperature=current.get("temp", 0),
                feels_like=current.get("feels_like", 0),
                humidity=current.get("humidity", 0),
                description=weather.get("description", ""),
                icon=weather.get("icon", ""),
                wind_speed=current.get("wind_speed", 0)
            )
            
            # Forecast
            if include_forecast:
                forecasts = []
                daily_data = data.get("daily", [])[:7]
                
                for day in daily_data:
                    forecast = WeatherForecast(
                        date=datetime.fromtimestamp(day.get("dt", 0)),
                        temperature_max=day.get("temp", {}).get("max", 0),
                        temperature_min=day.get("temp", {}).get("min", 0),
                        description=day.get("weather", [{}])[0].get("description", ""),
                        icon=day.get("weather", [{}])[0].get("icon", ""),
                        precipitation_probability=day.get("pop", 0) * 100
                    )
                    forecasts.append(forecast)
                
                result["forecast"] = forecasts
            
            # Alerts
            alerts = []
            alerts_data = data.get("alerts", [])
            
            for alert_data in alerts_data:
                severity = self._determine_severity(alert_data)
                
                if severity in settings.WEATHER_ALERT_TYPES:
                    alert = WeatherAlert(
                        event=alert_data.get("event", ""),
                        severity=severity,
                        description=alert_data.get("description", ""),
                        start_time=datetime.fromtimestamp(alert_data.get("start", 0)),
                        end_time=datetime.fromtimestamp(alert_data.get("end", 0))
                    )
                    alerts.append(alert)
            
            result["alerts"] = alerts
            
            return result
            
        except Exception as e:
            print(f"Error fetching complete weather data: {e}")
            return {
                "current": None,
                "forecast": [] if include_forecast else None,
                "alerts": []
            }
    
    def calculate_weather_score(
        self,
        current: WeatherCondition,
        alerts: List[WeatherAlert]
    ) -> float:
        """
        Calculate a weather suitability score (0-1)
        
        Higher scores indicate better weather for tourism
        
        Args:
            current: Current weather condition
            alerts: List of weather alerts
            
        Returns:
            Weather score between 0 and 1
        """
        score = 1.0
        
        # Temperature penalty (assume comfort range 15-25°C)
        temp = current.temperature
        if temp < 10 or temp > 30:
            score *= 0.7
        elif temp < 15 or temp > 25:
            score *= 0.85
        
        # Weather condition penalties
        description = current.description.lower()
        if "rain" in description or "drizzle" in description:
            score *= 0.6
        elif "snow" in description:
            score *= 0.5
        elif "storm" in description or "thunderstorm" in description:
            score *= 0.3
        elif "clouds" in description:
            score *= 0.9
        
        # Wind penalty
        if current.wind_speed > 10:  # m/s
            score *= 0.8
        
        # Alert penalties
        for alert in alerts:
            if alert.severity == "warning":
                score *= 0.3
            elif alert.severity == "watch":
                score *= 0.6
            elif alert.severity == "advisory":
                score *= 0.8
        
        return max(score, 0.0)


# Global instance
weather_service = WeatherService()