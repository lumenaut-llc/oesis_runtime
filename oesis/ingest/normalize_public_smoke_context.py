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


def validate_raw_public_smoke(payload: dict):
    required = [
        "source_name",
        "observed_at",
        "parcel_id",
        "regional_pm25_ugm3",
        "smoke_advisory_level",
    ]
    for field in required:
        require(field in payload, f"raw public smoke missing required field: {field}")

    require_type(payload["source_name"], str, "source_name")
    require_type(payload["observed_at"], str, "observed_at")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_number(payload["regional_pm25_ugm3"], "regional_pm25_ugm3", minimum=0)
    require(
        payload["smoke_advisory_level"] in {"none", "light", "moderate", "heavy"},
        "smoke_advisory_level invalid",
    )


def derive_smoke_probability(pm25: float, advisory_level: str) -> float:
    probability = 0.06
    if pm25 >= 55:
        probability = 0.45
    elif pm25 >= 35:
        probability = 0.28
    elif pm25 >= 12:
        probability = 0.14

    advisory_bonus = {
        "none": 0.0,
        "light": 0.03,
        "moderate": 0.08,
        "heavy": 0.15,
    }[advisory_level]

    return clamp_probability(probability + advisory_bonus)


def build_summary(payload: dict, smoke_probability: float) -> list[str]:
    summaries = []
    if smoke_probability >= 0.45:
        summaries.append("Regional smoke context suggests elevated smoke concern.")
    elif smoke_probability >= 0.2:
        summaries.append("Regional smoke context suggests modest smoke concern.")
    else:
        summaries.append("Regional smoke context does not currently suggest severe smoke concern.")

    summaries.append(
        f"Regional PM2.5 estimate is {payload['regional_pm25_ugm3']:.1f} ug/m3 with a {payload['smoke_advisory_level']} advisory level."
    )
    return summaries


def normalize_public_smoke_context(payload: dict) -> dict:
    validate_raw_public_smoke(payload)

    smoke_probability = derive_smoke_probability(
        payload["regional_pm25_ugm3"],
        payload["smoke_advisory_level"],
    )

    return {
        "context_id": make_ref("pubctx"),
        "source_kind": "public_context",
        "source_name": payload["source_name"],
        "observed_at": payload["observed_at"],
        "coverage_mode": "regional",
        "parcel_id": payload["parcel_id"],
        "hazards": {
            "smoke_probability": smoke_probability,
            "heat_probability": 0.05,
            "flood_probability": 0.03,
        },
        "summary": build_summary(payload, smoke_probability),
        "raw_context": payload,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize a raw public smoke payload into the canonical public-context object."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "raw-public-smoke.example.json"),
        help="Path to a raw public smoke JSON file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()

    try:
        payload = load_json(input_path)
        normalized = normalize_public_smoke_context(payload)
    except (ValidationError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR {input_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(normalized, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
