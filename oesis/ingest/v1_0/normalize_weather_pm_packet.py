#!/usr/bin/env python3
"""Normalize a weather-pm-mast node packet into an air.pm.snapshot observation."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from oesis.common.runtime_lane import resolve_runtime_lane, versioning_payload


class WeatherPmValidationError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def validate_weather_pm_packet(payload: dict) -> None:
    required = [
        "schema_version", "node_id", "firmware_version",
        "observed_at", "location_mode", "sensors", "health",
    ]
    for field in required:
        if field not in payload:
            raise WeatherPmValidationError(f"weather-pm-mast packet missing required field: {field}")

    if payload["schema_version"] != "oesis.weather-pm-mast.v1":
        raise WeatherPmValidationError(
            f"schema_version must be oesis.weather-pm-mast.v1, got {payload['schema_version']!r}"
        )

    sensors = payload["sensors"]
    if not isinstance(sensors, dict):
        raise WeatherPmValidationError("sensors must be an object")

    health = payload["health"]
    if not isinstance(health, dict):
        raise WeatherPmValidationError("health must be an object")


def _get_bme_payload(sensors: dict) -> dict:
    return sensors.get("bme680") or sensors.get("bme688") or {}


def build_weather_pm_values(payload: dict) -> dict:
    sensors = payload["sensors"]
    derived = deepcopy(payload.get("derived", {}))
    sht45 = sensors.get("sht45", {})
    bme = _get_bme_payload(sensors)
    sps30 = sensors.get("sps30", {})

    sht45_present = bool(sht45.get("present"))
    bme_present = bool(bme.get("present"))
    sps30_present = bool(sps30.get("present"))

    values: dict = {}

    # Temperature: prefer derived, then SHT45, then BME
    if sht45_present and "temperature_c_primary" in derived and derived["temperature_c_primary"] is not None:
        values["temperature_c_primary"] = derived["temperature_c_primary"]
    elif sht45_present and "temperature_c" in sht45:
        values["temperature_c_primary"] = sht45["temperature_c"]
    elif bme_present and "temperature_c" in bme:
        values["temperature_c_primary"] = bme["temperature_c"]

    # Humidity: prefer derived, then SHT45, then BME
    if sht45_present and "relative_humidity_pct_primary" in derived and derived["relative_humidity_pct_primary"] is not None:
        values["relative_humidity_pct_primary"] = derived["relative_humidity_pct_primary"]
    elif sht45_present and "relative_humidity_pct" in sht45:
        values["relative_humidity_pct_primary"] = sht45["relative_humidity_pct"]
    elif bme_present and "relative_humidity_pct" in bme:
        values["relative_humidity_pct_primary"] = bme["relative_humidity_pct"]

    # Pressure from BME
    if bme_present and "pressure_hpa" in derived and derived["pressure_hpa"] is not None:
        values["pressure_hpa"] = derived["pressure_hpa"]
    elif bme_present and "pressure_hpa" in bme:
        values["pressure_hpa"] = bme["pressure_hpa"]

    # Gas resistance from BME
    if bme_present and "gas_resistance_ohm" in bme:
        values["gas_resistance_ohm"] = bme["gas_resistance_ohm"]

    # VOC trend source
    if bme_present and "voc_trend_source" in derived and derived["voc_trend_source"] is not None:
        values["voc_trend_source"] = derived["voc_trend_source"]

    # SPS30 PM fields
    if sps30_present:
        for field in ("pm1_ugm3", "pm25_ugm3", "pm4_ugm3", "pm10_ugm3", "typical_particle_size_um"):
            if field in sps30:
                values[field] = sps30[field]

    # Derived pm25_ugm3 (from derived block, for direct smoke evidence)
    if "pm25_ugm3" in derived and derived["pm25_ugm3"] is not None:
        values["pm25_ugm3"] = derived["pm25_ugm3"]

    return values


def normalize_weather_pm_packet(
    payload: dict,
    *,
    parcel_id: str | None = None,
    ingested_at: str | None = None,
    runtime_lane: str | None = None,
) -> dict:
    validate_weather_pm_packet(payload)
    ingested_at = ingested_at or now_iso()
    resolved_lane = resolve_runtime_lane(runtime_lane)

    return {
        "observation_id": make_ref("obs"),
        "node_id": payload["node_id"],
        "parcel_id": parcel_id,
        "observed_at": payload["observed_at"],
        "ingested_at": ingested_at,
        "observation_type": "air.pm.snapshot",
        "values": build_weather_pm_values(payload),
        "health": {
            "uptime_s": payload["health"]["uptime_s"],
            "wifi_connected": payload["health"].get("wifi_connected", False),
            "free_heap_bytes": payload["health"].get("free_heap_bytes"),
            "read_failures_total": payload["health"].get("read_failures_total", 0),
        },
        "provenance": {
            "source_kind": "weather_pm_node",
            "schema_version": payload["schema_version"],
            "firmware_version": payload["firmware_version"],
            "raw_packet_ref": make_ref("rawpkt"),
        },
        "versioning": versioning_payload(lane=resolved_lane),
        "raw_packet": payload,
    }
