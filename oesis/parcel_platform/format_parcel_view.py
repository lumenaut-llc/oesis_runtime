#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR

EXAMPLES_DIR = DOCS_EXAMPLES_DIR


class ParcelViewError(Exception):
    pass


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_parcel_state(payload: dict):
    required = [
        "parcel_id",
        "computed_at",
        "shelter_status",
        "reentry_status",
        "egress_status",
        "asset_risk_status",
        "confidence",
        "evidence_mode",
        "inference_basis",
        "explanation_payload",
        "reasons",
        "hazards",
        "freshness",
        "provenance_summary",
    ]
    for field in required:
        if field not in payload:
            raise ParcelViewError(f"parcel state missing required field: {field}")


def validate_sharing_settings(payload: dict):
    required = [
        "parcel_id",
        "updated_at",
        "private_only",
        "network_assist",
        "neighborhood_aggregate",
        "research_or_pilot",
        "notice_version",
        "revocation_pending",
    ]
    for field in required:
        if field not in payload:
            raise ParcelViewError(f"sharing settings missing required field: {field}")


def format_summary(payload: dict) -> str:
    statuses = {
        "shelter": payload["shelter_status"],
        "reentry": payload["reentry_status"],
        "egress": payload["egress_status"],
        "asset_risk": payload["asset_risk_status"],
    }
    priority = {
        "unsafe": 3,
        "caution": 2,
        "safe": 1,
        "unknown": 0,
    }
    dominant_status = max(statuses.values(), key=lambda value: priority.get(value, -1))
    return (
        f"Parcel status is {dominant_status} with "
        f"{int(round(payload['confidence'] * 100))}% confidence "
        f"based on {payload['evidence_mode'].replace('_', ' ')} evidence."
    )


def default_sharing_settings(parcel_id: str) -> dict:
    return {
        "parcel_id": parcel_id,
        "updated_at": "",
        "private_only": True,
        "network_assist": False,
        "neighborhood_aggregate": False,
        "research_or_pilot": False,
        "notice_version": "sharing-notice.v1",
        "revocation_pending": False,
    }


def build_parcel_view(payload: dict, sharing_settings: dict | None = None) -> dict:
    validate_parcel_state(payload)
    sharing_settings = sharing_settings or default_sharing_settings(payload["parcel_id"])
    validate_sharing_settings(sharing_settings)

    data_classes_visible = ["private_parcel_data", "derived_parcel_state"]
    if "public" in payload["inference_basis"]:
        data_classes_visible.append("public_context")
    if "shared" in payload["inference_basis"] or sharing_settings["neighborhood_aggregate"]:
        data_classes_visible.append("shared_data")

    return {
        "parcel_id": payload["parcel_id"],
        "computed_at": payload["computed_at"],
        "statuses": {
            "shelter": payload["shelter_status"],
            "reentry": payload["reentry_status"],
            "egress": payload["egress_status"],
            "asset_risk": payload["asset_risk_status"],
        },
        "confidence": payload["confidence"],
        "evidence_mode": payload["evidence_mode"],
        "inference_basis": payload["inference_basis"],
        "explanation_payload": payload["explanation_payload"],
        "summary": format_summary(payload),
        "reasons": payload["reasons"],
        "hazards": payload["hazards"],
        "freshness": payload["freshness"],
        "provenance_summary": payload["provenance_summary"],
        "data_classes_visible": data_classes_visible,
        "sharing_summary": {
            "private_only": sharing_settings["private_only"],
            "network_assist": sharing_settings["network_assist"],
            "neighborhood_aggregate": sharing_settings["neighborhood_aggregate"],
            "research_or_pilot": sharing_settings["research_or_pilot"],
            "notice_version": sharing_settings["notice_version"],
            "revocation_pending": sharing_settings["revocation_pending"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Format a parcel-state snapshot into a parcel-platform response.")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "parcel-state.example.json"),
        help="Path to a parcel-state JSON file.",
    )
    parser.add_argument(
        "--sharing-settings",
        default=str(EXAMPLES_DIR / "sharing-settings.example.json"),
        help="Path to a sharing-settings JSON file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()

    try:
        payload = load_json(input_path)
        sharing_settings = load_json(Path(args.sharing_settings).resolve())
        formatted = build_parcel_view(payload, sharing_settings)
    except (ParcelViewError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR {input_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(formatted, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
