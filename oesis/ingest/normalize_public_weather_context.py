#!/usr/bin/env python3

import argparse
import json
import sys
import uuid
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR

from .validate_examples import ValidationError, load_json, require, require_number, require_type


EXAMPLES_DIR = DOCS_EXAMPLES_DIR


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def make_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def validate_raw_public_weather(payload: dict):
    required = [
        "source_name",
        "observed_at",
        "parcel_id",
        "regional_temperature_c",
        "regional_relative_humidity_pct",
        "advisories",
    ]
    for field in required:
        require(field in payload, f"raw public weather missing required field: {field}")

    require_type(payload["source_name"], str, "source_name")
    require_type(payload["observed_at"], str, "observed_at")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_number(payload["regional_temperature_c"], "regional_temperature_c")
    require_number(
        payload["regional_relative_humidity_pct"],
        "regional_relative_humidity_pct",
        minimum=0,
        maximum=100,
    )
    require_type(payload["advisories"], list, "advisories")


def derive_heat_probability(temperature_c: float, humidity_pct: float) -> float:
    probability = 0.1
    if temperature_c >= 34:
        probability = 0.55
    elif temperature_c >= 29:
        probability = 0.36
    elif temperature_c >= 24:
        probability = 0.2

    if humidity_pct >= 55:
        probability += 0.06

    return clamp_probability(probability)


def build_summary(payload: dict, heat_probability: float) -> list[str]:
    summaries = []
    if heat_probability >= 0.5:
        summaries.append("Regional conditions suggest elevated heat concern.")
    elif heat_probability >= 0.3:
        summaries.append("Regional conditions suggest modest heat concern.")
    else:
        summaries.append("Regional weather does not currently suggest strong heat concern.")

    if "warm_afternoon" in payload.get("advisories", []):
        summaries.append("Regional weather source reports a warm afternoon pattern.")

    return summaries


def normalize_public_weather_context(payload: dict) -> dict:
    validate_raw_public_weather(payload)

    heat_probability = derive_heat_probability(
        payload["regional_temperature_c"],
        payload["regional_relative_humidity_pct"],
    )
    smoke_probability = 0.05
    flood_probability = 0.03

    return {
        "context_id": make_ref("pubctx"),
        "source_kind": "public_context",
        "source_name": payload["source_name"],
        "observed_at": payload["observed_at"],
        "coverage_mode": "regional",
        "parcel_id": payload["parcel_id"],
        "hazards": {
            "smoke_probability": smoke_probability,
            "heat_probability": heat_probability,
            "flood_probability": flood_probability,
        },
        "summary": build_summary(payload, heat_probability),
        "raw_context": payload,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize a raw public weather payload into the canonical public-context object."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "raw-public-weather.example.json"),
        help="Path to a raw public weather JSON file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()

    try:
        payload = load_json(input_path)
        normalized = normalize_public_weather_context(payload)
    except (ValidationError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR {input_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(normalized, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
