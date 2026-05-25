"""
Weather Skill - Gets weather information from API
Example of an external API integration skill
"""

import os
import requests
from typing import Any, Dict
from skills.base import Skill


class WeatherSkill(Skill):
    name = "weather"

    def __init__(self):
        # Get API key from environment variable
        # Add WEATHER_API_KEY=your_key to .env file
        self.api_key = os.getenv("WEATHER_API_KEY")
        self.base_url = "http://api.openweathermap.org/data/2.5/weather"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get weather information for a location
        
        Expected payload format:
        {
            "location": "New York",     # City name or "lat,lon" coordinates
            "units": "metric"           # Optional: "metric", "imperial", "kelvin"
        }
        """
        payload = task.get("payload", {})
        location = payload.get("location", "")
        units = payload.get("units", "metric")
        
        if not location:
            return {
                "error": "No location provided", 
                "task_id": task.get("id"),
                "examples": ["New York", "London", "40.7128,-74.0060"]
            }
        
        if not self.api_key:
            return {
                "error": "Weather API key not configured",
                "task_id": task.get("id"),
                "setup_instructions": "Add WEATHER_API_KEY to your .env file"
            }
        
        try:
            weather_data = self._get_weather(location, units)
            return {
                "location": weather_data["name"],
                "country": weather_data["sys"]["country"],
                "temperature": weather_data["main"]["temp"],
                "feels_like": weather_data["main"]["feels_like"],
                "humidity": weather_data["main"]["humidity"],
                "description": weather_data["weather"][0]["description"],
                "wind_speed": weather_data["wind"]["speed"],
                "units": units,
                "task_id": task.get("id"),
                "status": "success"
            }
            
        except requests.RequestException as e:
            return {
                "error": f"API request failed: {str(e)}",
                "location": location,
                "task_id": task.get("id"),
                "status": "error"
            }
        except KeyError as e:
            return {
                "error": f"Unexpected API response format: {str(e)}",
                "location": location, 
                "task_id": task.get("id"),
                "status": "error"
            }
    
    def _get_weather(self, location: str, units: str) -> Dict[str, Any]:
        """Get weather data from OpenWeatherMap API"""
        # Determine if location is coordinates or city name
        if "," in location and self._is_coordinates(location):
            lat, lon = location.split(",")
            params = {
                "lat": lat.strip(),
                "lon": lon.strip(),
                "appid": self.api_key,
                "units": units
            }
        else:
            params = {
                "q": location,
                "appid": self.api_key,
                "units": units
            }
        
        response = requests.get(self.base_url, params=params, timeout=10)
        
        if response.status_code == 404:
            raise requests.RequestException("Location not found")
        elif response.status_code == 401:
            raise requests.RequestException("Invalid API key")
        elif response.status_code != 200:
            raise requests.RequestException(f"API error: {response.status_code}")
        
        return response.json()
    
    def _is_coordinates(self, location: str) -> bool:
        """Check if location string contains valid coordinates"""
        try:
            parts = location.split(",")
            if len(parts) != 2:
                return False
            lat, lon = float(parts[0].strip()), float(parts[1].strip())
            return -90 <= lat <= 90 and -180 <= lon <= 180
        except ValueError:
            return False