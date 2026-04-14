"""Normalize oesis.flood-node.v1 packets into flood.low_point.snapshot observations."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from oesis.common.runtime_lane import resolve_runtime_lane, versioning_payload


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def validate_flood_packet(payload: dict) -> None:
    if payload.get("schema_version") != "oesis.flood-node.v1":
        raise ValueError(f"expected schema_version oesis.flood-node.v1, got {payload.get('schema_version')}")
    for key in ("node_id", "observed_at", "firmware_version", "sensors", "derived", "health"):
        if key not in payload:
            raise ValueError(f"flood packet missing required field: {key}")
    sensors = payload["sensors"]
    if "mb7389" not in sensors:
        raise ValueError("flood packet missing mb7389 sensor")
    mb7389 = sensors["mb7389"]
    for field in ("present", "distance_cm"):
        if field not in mb7389:
            raise ValueError(f"mb7389 sensor missing field: {field}")
    derived = payload["derived"]
    for field in ("water_depth_cm", "dry_reference_distance_cm"):
        if field not in derived:
            raise ValueError(f"flood derived missing field: {field}")


def build_flood_values(payload: dict) -> dict:
    sensors = payload["sensors"]
    derived = deepcopy(payload.get("derived", {}))
    mb7389 = sensors["mb7389"]

    values = {
        "distance_cm": mb7389["distance_cm"],
        "water_depth_cm": derived["water_depth_cm"],
        "dry_reference_distance_cm": derived["dry_reference_distance_cm"],
    }
    if "rise_rate_cm_per_hr" in derived:
        values["rise_rate_cm_per_hr"] = derived["rise_rate_cm_per_hr"]
    if "calibration_state" in derived:
        values["calibration_state"] = derived["calibration_state"]
    if "analog_raw" in mb7389:
        values["analog_raw"] = mb7389["analog_raw"]
    if "sensor_voltage_v" in mb7389:
        values["sensor_voltage_v"] = mb7389["sensor_voltage_v"]
    return values


def normalize_flood_packet(
    payload: dict,
    *,
    parcel_id: str | None = None,
    ingested_at: str | None = None,
    runtime_lane: str | None = None,
) -> dict:
    validate_flood_packet(payload)
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
            "read_failures_total": payload["health"]["read_failures_total"],
        },
        "provenance": {
            "source_kind": "dwelling_node",
            "schema_version": payload["schema_version"],
            "firmware_version": payload["firmware_version"],
            "raw_packet_ref": make_ref("rawpkt"),
        },
        "versioning": versioning_payload(lane=resolved_lane),
        "raw_packet": payload,
    }
