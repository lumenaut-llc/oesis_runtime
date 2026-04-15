#!/usr/bin/env python3
"""Normalize a circuit-monitor node packet into an equipment.circuit.snapshot observation."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from oesis.common.runtime_lane import resolve_runtime_lane, versioning_payload


class CircuitValidationError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


VALID_INFERRED_STATES = {
    "off", "fan_only", "compressor_running", "heating_active",
    "standby", "starting", "running", "overload", "unknown",
}


def validate_circuit_monitor_packet(payload: dict) -> None:
    required = [
        "schema_version", "node_id", "firmware_version",
        "uptime_s", "observed_at", "circuits", "health",
    ]
    for field in required:
        if field not in payload:
            raise CircuitValidationError(f"circuit monitor packet missing required field: {field}")

    # Accept both schema_version (canonical) and legacy schema_id
    schema = payload.get("schema_version") or payload.get("schema_id", "")
    if schema != "oesis.circuit-monitor.v1":
        raise CircuitValidationError(f"schema_version must be oesis.circuit-monitor.v1, got {schema!r}")

    circuits = payload["circuits"]
    if not isinstance(circuits, list) or len(circuits) == 0:
        raise CircuitValidationError("circuits must be a non-empty array")

    for i, circuit in enumerate(circuits):
        for f in ("circuit_id", "current_a", "power_w", "voltage_v", "power_factor",
                  "energy_kwh", "inferred_state", "cycle_active"):
            if f not in circuit:
                raise CircuitValidationError(f"circuits[{i}] missing required field: {f}")
        if circuit["inferred_state"] not in VALID_INFERRED_STATES:
            raise CircuitValidationError(f"circuits[{i}].inferred_state invalid: {circuit['inferred_state']!r}")

    health = payload["health"]
    if not isinstance(health, dict):
        raise CircuitValidationError("health must be an object")


def build_circuit_values(payload: dict) -> dict:
    return {
        "circuits": [
            {
                "circuit_id": c["circuit_id"],
                "current_a": c["current_a"],
                "power_w": c["power_w"],
                "voltage_v": c["voltage_v"],
                "power_factor": c["power_factor"],
                "energy_kwh": c["energy_kwh"],
                "inferred_state": c["inferred_state"],
                "cycle_active": c["cycle_active"],
                "cycle_duration_s": c.get("cycle_duration_s"),
            }
            for c in payload["circuits"]
        ]
    }


def normalize_circuit_packet(
    payload: dict,
    *,
    parcel_id: str | None = None,
    ingested_at: str | None = None,
    runtime_lane: str | None = None,
) -> dict:
    validate_circuit_monitor_packet(payload)
    ingested_at = ingested_at or now_iso()
    resolved_lane = resolve_runtime_lane(runtime_lane)

    return {
        "observation_id": make_ref("obs"),
        "node_id": payload["node_id"],
        "parcel_id": parcel_id,
        "observed_at": payload["observed_at"],
        "ingested_at": ingested_at,
        "observation_type": "equipment.circuit.snapshot",
        "values": build_circuit_values(payload),
        "health": {
            "uptime_s": payload["uptime_s"],
            "wifi_rssi": payload["health"].get("wifi_rssi"),
            "heap_free": payload["health"].get("heap_free"),
            "sample_interval_ms": payload["health"].get("sample_interval_ms"),
            "read_failures_total": payload["health"].get("read_failures_total", 0),
        },
        "provenance": {
            "source_kind": "circuit_monitor_node",
            "schema_version": payload.get("schema_version") or payload.get("schema_id", "oesis.circuit-monitor.v1"),
            "firmware_version": payload["firmware_version"],
            "raw_packet_ref": make_ref("rawpkt"),
        },
        "versioning": versioning_payload(lane=resolved_lane),
        "raw_packet": payload,
    }
