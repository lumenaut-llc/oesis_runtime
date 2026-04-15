#!/usr/bin/env python3
"""Normalize a flood-node packet into a flood.low_point.snapshot observation."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from oesis.common.runtime_lane import resolve_runtime_lane, versioning_payload


class FloodValidationError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


VALID_CALIBRATION_STATES = {"provisional", "field_validated", "factory"}


def validate_flood_node_packet(payload: dict) -> None:
    required = [
        "schema_version", "node_id", "firmware_version",
        "observed_at", "location_mode", "install_role",
        "sensors", "derived", "health",
    ]
    for field in required:
        if field not in payload:
            raise FloodValidationError(f"flood node packet missing required field: {field}")

    if payload["schema_version"] != "oesis.flood-node.v1":
        raise FloodValidationError(f"schema_version must be oesis.flood-node.v1, got {payload['schema_version']!r}")

    sensors = payload["sensors"]
    if not isinstance(sensors, dict):
        raise FloodValidationError("sensors must be an object")
    if "mb7389" not in sensors:
        raise FloodValidationError("sensors missing required key: mb7389")

    mb7389 = sensors["mb7389"]
    if not isinstance(mb7389, dict):
        raise FloodValidationError("sensors.mb7389 must be an object")
    for f in ("present", "analog_raw", "sensor_voltage_v", "distance_cm"):
        if f not in mb7389:
            raise FloodValidationError(f"sensors.mb7389 missing required field: {f}")

    derived = payload["derived"]
    if not isinstance(derived, dict):
        raise FloodValidationError("derived must be an object")
    for f in ("dry_reference_distance_cm", "water_depth_cm", "rise_rate_cm_per_hr", "calibration_state"):
        if f not in derived:
            raise FloodValidationError(f"derived missing required field: {f}")
    if derived["calibration_state"] not in VALID_CALIBRATION_STATES:
        raise FloodValidationError(f"derived.calibration_state invalid: {derived['calibration_state']!r}")

    health = payload["health"]
    if not isinstance(health, dict):
        raise FloodValidationError("health must be an object")


def build_flood_values(payload: dict) -> dict:
    mb7389 = payload["sensors"]["mb7389"]
    derived = payload["derived"]
    return {
        "distance_cm": mb7389["distance_cm"],
        "sensor_voltage_v": mb7389["sensor_voltage_v"],
        "analog_raw": mb7389["analog_raw"],
        "dry_reference_distance_cm": derived["dry_reference_distance_cm"],
        "water_depth_cm": derived["water_depth_cm"],
        "rise_rate_cm_per_hr": derived["rise_rate_cm_per_hr"],
        "calibration_state": derived["calibration_state"],
    }


def normalize_flood_packet(
    payload: dict,
    *,
    parcel_id: str | None = None,
    ingested_at: str | None = None,
    runtime_lane: str | None = None,
) -> dict:
    validate_flood_node_packet(payload)
    ingested_at = ingested_at or now_iso()
    resolved_lane = resolve_runtime_lane(runtime_lane)

    return {
        "observation_id": make_ref("obs"),
        "node_id": payload["node_id"],
        "parcel_id": parcel_id,
        "observed_at": payload["observed_at"],
        "ingested_at": ingested_at,
        "observation_type": "flood.low_point.snapshot",
        "values": build_flood_values(payload),
        "health": {
            "uptime_s": payload["health"]["uptime_s"],
            "wifi_connected": payload["health"]["wifi_connected"],
            "free_heap_bytes": payload["health"]["free_heap_bytes"],
            "read_failures_total": payload["health"]["read_failures_total"],
        },
        "provenance": {
            "source_kind": "flood_node",
            "schema_version": payload["schema_version"],
            "firmware_version": payload["firmware_version"],
            "raw_packet_ref": make_ref("rawpkt"),
        },
        "versioning": versioning_payload(lane=resolved_lane),
        "raw_packet": payload,
    }
