#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR

from .format_parcel_view import ParcelViewError, load_json, validate_parcel_state


EXAMPLES_DIR = DOCS_EXAMPLES_DIR


def group_contributions(evidence_contributions: list[dict]) -> dict:
    grouped = {
        "local": [],
        "shared": [],
        "public": [],
        "parcel_context": [],
        "system": [],
    }
    for contribution in evidence_contributions:
        grouped[contribution["source_class"]].append(contribution)
    for key in grouped:
        grouped[key] = sorted(grouped[key], key=lambda item: item["weight"], reverse=True)
    return grouped


def build_evidence_summary(payload: dict) -> dict:
    validate_parcel_state(payload)

    explanation = payload["explanation_payload"]
    grouped = group_contributions(explanation["evidence_contributions"])

    return {
        "parcel_id": payload["parcel_id"],
        "computed_at": payload["computed_at"],
        "evidence_mode": payload["evidence_mode"],
        "inference_basis": payload["inference_basis"],
        "confidence": payload["confidence"],
        "headline": explanation["headline"],
        "confidence_band": explanation["basis"]["confidence_band"],
        "top_drivers": explanation["drivers"],
        "top_limitations": explanation["limitations"],
        "source_breakdown": explanation["source_breakdown"],
        "grouped_contributions": grouped,
        "source_modes": payload["provenance_summary"]["source_modes"],
        "freshness": payload["freshness"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Format a parcel-state snapshot into an evidence-summary response.")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "parcel-state.example.json"),
        help="Path to a parcel-state JSON file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()

    try:
        payload = load_json(input_path)
        formatted = build_evidence_summary(payload)
    except (ParcelViewError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR {input_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(formatted, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
