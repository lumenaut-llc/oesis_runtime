"""AirNow API adapter for live PM2.5 and smoke advisory data.

API docs: https://docs.airnowapi.org/CurrentObservationsByZip/docs
Requires an API key from https://docs.airnowapi.org/account/request/

Environment variable: OESIS_AIRNOW_API_KEY
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone


AIRNOW_BASE_URL = "https://www.airnowapi.org/aq/observation/zipCode/current/"

# AQI category → smoke advisory level mapping
AQI_TO_ADVISORY = {
    1: "none",           # Good (0-50)
    2: "none",           # Moderate (51-100)
    3: "advisory",       # Unhealthy for Sensitive Groups (101-150)
    4: "warning",        # Unhealthy (151-200)
    5: "alert",          # Very Unhealthy (201-300)
    6: "emergency",      # Hazardous (301-500)
}


def fetch_airnow_pm25(
    api_key: str,
    zip_code: str,
    *,
    timeout_seconds: int = 30,
) -> dict | None:
    """Fetch current PM2.5 observation from AirNow for a zip code.

    Returns a dict in the raw-public-smoke format expected by
    normalize_public_smoke_context, or None if the API call fails
    or no PM2.5 data is available.
    """
    params = (
        f"?format=application/json"
        f"&zipCode={zip_code}"
        f"&distance=25"
        f"&API_KEY={api_key}"
    )
    url = AIRNOW_BASE_URL + params

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.request.URLError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, list) or not data:
        return None

    # Find PM2.5 observation (ParameterName == "PM2.5")
    pm25_obs = None
    for obs in data:
        if obs.get("ParameterName") == "PM2.5":
            pm25_obs = obs
            break

    if pm25_obs is None:
        return None

    aqi = pm25_obs.get("AQI", 0)
    category = pm25_obs.get("Category", {})
    category_number = category.get("Number", 1) if isinstance(category, dict) else 1

    # Convert AQI to approximate PM2.5 concentration (EPA breakpoint table)
    pm25_ugm3 = _aqi_to_pm25(aqi)

    observed_at = pm25_obs.get("DateObserved", "")
    hour = pm25_obs.get("HourObserved", 0)
    try:
        obs_dt = datetime.strptime(f"{observed_at.strip()} {hour:02d}:00", "%Y-%m-%d %H:%M")
        obs_iso = obs_dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        obs_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return {
        "source_name": "airnow",
        "observed_at": obs_iso,
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "regional_pm25_ugm3": round(pm25_ugm3, 1),
        "aqi": aqi,
        "smoke_advisory_level": AQI_TO_ADVISORY.get(category_number, "none"),
        "reporting_area": pm25_obs.get("ReportingArea", "unknown"),
        "state_code": pm25_obs.get("StateCode", ""),
    }


def _aqi_to_pm25(aqi: int) -> float:
    """Approximate PM2.5 concentration from AQI using EPA breakpoints."""
    breakpoints = [
        (0, 50, 0.0, 12.0),
        (51, 100, 12.1, 35.4),
        (101, 150, 35.5, 55.4),
        (151, 200, 55.5, 150.4),
        (201, 300, 150.5, 250.4),
        (301, 500, 250.5, 500.4),
    ]
    for aqi_lo, aqi_hi, pm_lo, pm_hi in breakpoints:
        if aqi_lo <= aqi <= aqi_hi:
            return pm_lo + (aqi - aqi_lo) * (pm_hi - pm_lo) / (aqi_hi - aqi_lo)
    return float(aqi)  # fallback
