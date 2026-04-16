"""Orchestrate public feed fetching with cache and graceful degradation.

Usage:
    manager = PublicFeedManager()
    smoke_ctx, mode = manager.get_smoke_context("parcel_001")
    weather_ctx, mode = manager.get_weather_context("parcel_001")

Evidence mode returned:
- "local_plus_public": fresh data from live feed
- "degraded": using stale cached data (feed unavailable)
- None: no data available at all (use fixture fallback)
"""

from __future__ import annotations

import os
from pathlib import Path

from .airnow_adapter import fetch_airnow_pm25
from .feed_cache import FeedCache
from .noaa_adapter import fetch_noaa_weather


# Default staleness thresholds (seconds)
SMOKE_TTL = 3600       # 1 hour
WEATHER_TTL = 21600    # 6 hours


class PublicFeedManager:
    """Manage live public feed fetching with caching and fallback."""

    def __init__(
        self,
        *,
        airnow_api_key: str | None = None,
        airnow_zip_code: str | None = None,
        noaa_station_id: str | None = None,
        cache_dir: str | Path | None = None,
        smoke_ttl: int = SMOKE_TTL,
        weather_ttl: int = WEATHER_TTL,
    ):
        self.airnow_api_key = airnow_api_key or os.environ.get("OESIS_AIRNOW_API_KEY")
        self.airnow_zip_code = airnow_zip_code or os.environ.get("OESIS_AIRNOW_ZIP_CODE", "97201")
        self.noaa_station_id = noaa_station_id or os.environ.get("OESIS_NOAA_STATION_ID")
        self.smoke_ttl = smoke_ttl
        self.weather_ttl = weather_ttl

        cache_path = cache_dir or os.environ.get("OESIS_FEED_CACHE_DIR")
        self._cache = FeedCache(cache_dir=cache_path)

    def get_smoke_context(self, parcel_id: str) -> tuple[dict | None, str | None]:
        """Fetch smoke/PM2.5 context with cache and fallback.

        Returns (context_dict, evidence_mode_hint) where:
        - evidence_mode_hint is "local_plus_public" for fresh, "degraded" for stale
        - Returns (None, None) if no data available at all
        """
        if not self.airnow_api_key:
            return None, None

        cache_key = f"smoke_{self.airnow_zip_code}"

        # Try fresh cache
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached, "local_plus_public"

        # Try live fetch
        fetched = fetch_airnow_pm25(
            self.airnow_api_key,
            self.airnow_zip_code,
        )
        if fetched is not None:
            self._cache.put(cache_key, fetched, self.smoke_ttl)
            return fetched, "local_plus_public"

        # Try stale cache (degraded mode)
        stale = self._cache.get_stale(cache_key)
        if stale is not None:
            return stale, "degraded"

        return None, None

    def get_weather_context(self, parcel_id: str) -> tuple[dict | None, str | None]:
        """Fetch weather context with cache and fallback.

        Returns (None, None) — NOAA adapter not yet implemented.
        """
        if not self.noaa_station_id:
            return None, None

        cache_key = f"weather_{self.noaa_station_id}"

        # Try fresh cache
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached, "local_plus_public"

        # Try live fetch (stub — always returns None)
        fetched = fetch_noaa_weather(self.noaa_station_id)
        if fetched is not None:
            self._cache.put(cache_key, fetched, self.weather_ttl)
            return fetched, "local_plus_public"

        # Try stale cache
        stale = self._cache.get_stale(cache_key)
        if stale is not None:
            return stale, "degraded"

        return None, None
