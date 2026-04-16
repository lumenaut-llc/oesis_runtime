"""NOAA Weather API adapter — stub for future implementation.

When implemented, this will fetch temperature, humidity, wind, and pressure
from NOAA's Weather API and map to the raw-public-weather format expected by
normalize_public_weather_context.

API docs: https://www.weather.gov/documentation/services-web-api
"""

from __future__ import annotations


def fetch_noaa_weather(
    station_id: str,
    *,
    timeout_seconds: int = 30,
) -> dict | None:
    """Fetch current weather observation from NOAA.

    Returns None — not yet implemented. When implemented, returns a dict
    in the raw-public-weather format.
    """
    return None
