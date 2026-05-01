#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from oesis.common.repo_paths import EXAMPLES_DIR
from oesis.common.runtime_lane import resolve_runtime_lane, versioning_payload

from .admissibility import compute_admissibility
from .normalize_circuit_packet import normalize_circuit_packet as _normalize_circuit
from .normalize_flood_packet import normalize_flood_packet as _normalize_flood
from .normalize_weather_pm_packet import normalize_weather_pm_packet as _normalize_weather_pm
from .validate_examples import ValidationError, load_json, validate_node_observation


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def get_bme_payload(sensors: dict) -> dict:
    return sensors.get("bme688") or sensors.get("bme680") or {}


def has_value(payload: dict, field_name: str) -> bool:
    return field_name in payload and payload[field_name] is not None


def build_admissibility_facts(payload: dict) -> dict:
    """
    Extract admissibility facts from a raw bench-air payload.

    Per ADR 0009 / G17, the v1.0 node-observation schema carries six optional
    calibration §C fact fields. We pass them straight through to
    compute_admissibility along with identity, location_mode, and health —
    the pure function tolerates missing keys (each absence becomes its
    own reason code, which is the policy-correct outcome).

    The v0.1-era payloads (no admissibility fact fields) flow through the
    same path; they will be stamped inadmissible with multiple reason
    codes — this is intentional. v0.1 fixtures should not be admitted to
    coefficient fitting until producers emit the v1.0 facts.
    """
    return {
        # Identity (§C check 1)
        "node_id": payload.get("node_id"),
        "firmware_version": payload.get("firmware_version"),
        # Producer-side intent vs verified install (§C check 3)
        "location_mode": payload.get("location_mode"),
        "node_deployment_class": payload.get("node_deployment_class"),
        # Maturity (§C check 2)
        "node_deployment_maturity": payload.get("node_deployment_maturity"),
        # Burn-in (§C check 4)
        "burn_in_complete": payload.get("burn_in_complete"),
        # Reference calibration (§C check 5). The schema carries
        # node_calibration_session_ref (string pointer) only; if a producer
        # also stamps node_calibration_verified_at the cadence check fires,
        # otherwise the reason code is gated on session_ref alone.
        "node_calibration_session_ref": payload.get("node_calibration_session_ref"),
        "node_calibration_verified_at": payload.get("node_calibration_verified_at"),
        # Placement representativeness (§C check 6)
        "placement_representativeness_class": payload.get("placement_representativeness_class"),
        # Protective fixture (§C check 7)
        "protective_fixture_verified_at": payload.get("protective_fixture_verified_at"),
        # Sensor health (§C check 8)
        "health": payload.get("health", {}),
    }


def build_values(payload: dict) -> dict:
    sensors = payload["sensors"]
    derived = deepcopy(payload.get("derived", {}))
    sht45_payload = sensors.get("sht45", {})
    bme_payload = get_bme_payload(sensors)
    sht45_present = bool(sht45_payload.get("present"))
    bme_present = bool(bme_payload.get("present"))

    values = {}
    if sht45_present and has_value(derived, "temperature_c_primary"):
        values["temperature_c_primary"] = derived["temperature_c_primary"]
    elif sht45_present:
        values["temperature_c_primary"] = sht45_payload["temperature_c"]
    elif bme_present:
        values["temperature_c_primary"] = bme_payload["temperature_c"]

    if sht45_present and has_value(derived, "relative_humidity_pct_primary"):
        values["relative_humidity_pct_primary"] = derived["relative_humidity_pct_primary"]
    elif sht45_present:
        values["relative_humidity_pct_primary"] = sht45_payload["relative_humidity_pct"]
    elif bme_present:
        values["relative_humidity_pct_primary"] = bme_payload["relative_humidity_pct"]

    if bme_present and has_value(derived, "pressure_hpa"):
        values["pressure_hpa"] = derived["pressure_hpa"]
    elif bme_present:
        values["pressure_hpa"] = bme_payload["pressure_hpa"]

    if bme_present:
        values["gas_resistance_ohm"] = bme_payload["gas_resistance_ohm"]

    if bme_present and has_value(derived, "voc_trend_source"):
        values["voc_trend_source"] = derived["voc_trend_source"]

    return values


def normalize_packet(
    payload: dict,
    *,
    parcel_id: str | None = None,
    ingested_at: str | None = None,
    runtime_lane: str | None = None,
) -> dict:
    # Dispatch to circuit-monitor normalizer if schema_version (or legacy schema_id) matches
    if payload.get("schema_version") == "oesis.circuit-monitor.v1" or payload.get("schema_id") == "oesis.circuit-monitor.v1":
        return _normalize_circuit(payload, parcel_id=parcel_id, ingested_at=ingested_at, runtime_lane=runtime_lane)

    # Dispatch to flood-node normalizer if schema_version matches
    if payload.get("schema_version") == "oesis.flood-node.v1":
        return _normalize_flood(payload, parcel_id=parcel_id, ingested_at=ingested_at, runtime_lane=runtime_lane)

    # Dispatch to weather-pm-mast normalizer if schema_version matches
    if payload.get("schema_version") == "oesis.weather-pm-mast.v1":
        return _normalize_weather_pm(payload, parcel_id=parcel_id, ingested_at=ingested_at, runtime_lane=runtime_lane)

    validate_node_observation(payload)
    ingested_at = ingested_at or now_iso()
    resolved_lane = resolve_runtime_lane(runtime_lane)

    # Compute admissibility per calibration-program §C / ADR 0009.
    # Bench-air packets always route to the physical-sensor path (tier=None);
    # adapter-derived sources flow through source-provenance-record, not here.
    admissibility = compute_admissibility(build_admissibility_facts(payload))

    normalized = {
        "observation_id": make_ref("obs"),
        "node_id": payload["node_id"],
        "parcel_id": parcel_id,
        "observed_at": payload["observed_at"],
        "ingested_at": ingested_at,
        "observation_type": "air.node.snapshot",
        "values": build_values(payload),
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
        # Per ADR 0009: admissibility decision lives on normalized observations
        # only, never back-propagated to the canonical schema. Empty reasons
        # list when admissible; populated reason codes when not.
        "admissible_to_calibration_dataset": admissibility.admissible,
        "admissibility_reasons": admissibility.reasons,
        "versioning": versioning_payload(lane=resolved_lane),
        "raw_packet": payload,
    }
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize a node packet into an MVP observation object.")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "node-observation.example.json"),
        help="Path to a node packet JSON file.",
    )
    parser.add_argument(
        "--parcel-id",
        default="parcel_demo_001",
        help="Optional parcel identifier to attach to the normalized observation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()

    try:
        payload = load_json(input_path)
        normalized = normalize_packet(payload, parcel_id=args.parcel_id)
    except (ValidationError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR {input_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(normalized, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
