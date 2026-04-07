#!/usr/bin/env python3

import argparse
import json
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR

from .validate_examples import ValidationError, load_json, validate_node_observation

EXAMPLES_DIR = DOCS_EXAMPLES_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def get_bme_payload(sensors: dict) -> dict:
    return sensors.get("bme688") or sensors.get("bme680") or {}


def has_value(payload: dict, field_name: str) -> bool:
    return field_name in payload and payload[field_name] is not None


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


def normalize_packet(payload: dict, *, parcel_id: str | None = None, ingested_at: str | None = None) -> dict:
    validate_node_observation(payload)
    ingested_at = ingested_at or now_iso()

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
            "source_kind": "homeowner_node",
            "schema_version": payload["schema_version"],
            "firmware_version": payload["firmware_version"],
            "raw_packet_ref": make_ref("rawpkt"),
        },
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
