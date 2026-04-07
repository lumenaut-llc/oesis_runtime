#!/usr/bin/env python3

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR

EXAMPLES_DIR = DOCS_EXAMPLES_DIR


class SharedMapError(Exception):
    pass


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str):
    if not condition:
        raise SharedMapError(message)


def validate_input(payload: dict):
    for field in ("generated_at", "min_participants", "sharing_settings", "contributions"):
        require(field in payload, f"shared map input missing required field: {field}")
    require(isinstance(payload["contributions"], list) and payload["contributions"], "contributions must not be empty")
    require(isinstance(payload["min_participants"], int) and payload["min_participants"] >= 1, "min_participants invalid")
    require(isinstance(payload["sharing_settings"], list), "sharing_settings must be a list")
    sharing_refs = set()
    for i, entry in enumerate(payload["sharing_settings"]):
        require(isinstance(entry, dict), f"sharing_settings[{i}] must be an object")
        for field in ("parcel_ref", "neighborhood_aggregate", "revocation_pending"):
            require(field in entry, f"sharing_settings[{i}] missing required field: {field}")
        require(isinstance(entry["parcel_ref"], str) and entry["parcel_ref"], f"sharing_settings[{i}].parcel_ref invalid")
        require(isinstance(entry["neighborhood_aggregate"], bool), f"sharing_settings[{i}].neighborhood_aggregate invalid")
        require(isinstance(entry["revocation_pending"], bool), f"sharing_settings[{i}].revocation_pending invalid")
        sharing_refs.add(entry["parcel_ref"])
    for i, contribution in enumerate(payload["contributions"]):
        require(isinstance(contribution, dict), f"contributions[{i}] must be an object")
        for field in ("cell_id", "source_class", "delayed_minutes", "hazards"):
            require(field in contribution, f"contributions[{i}] missing required field: {field}")
        require("parcel_id" not in contribution, f"contributions[{i}] must not include parcel_id")
        require(contribution["source_class"] in {"shared_data", "public_context"}, f"contributions[{i}].source_class invalid")
        if contribution["source_class"] == "shared_data":
            require("parcel_ref" in contribution, f"contributions[{i}] missing required field: parcel_ref")
            require(contribution["parcel_ref"] in sharing_refs, f"contributions[{i}].parcel_ref missing matching sharing_settings entry")


def load_sharing_store(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def eligibility_from_store(store: dict) -> dict:
    return {
        entry["parcel_ref"]: entry["sharing"]["neighborhood_aggregate"] and not entry["sharing"]["revocation_pending"]
        for entry in store["parcels"]
    }


def average_hazards(contributions: list[dict]) -> dict:
    if not contributions:
        return {
            "smoke_probability": 0.0,
            "flood_probability": 0.0,
            "heat_probability": 0.0,
        }
    totals = defaultdict(float)
    for contribution in contributions:
        for key, value in contribution["hazards"].items():
            totals[key] += value
    count = len(contributions)
    return {key: round(value / count, 3) for key, value in totals.items()}


def aggregate_shared_map(payload: dict, *, sharing_store: dict | None = None) -> dict:
    validate_input(payload)
    eligibility = (
        eligibility_from_store(sharing_store)
        if sharing_store is not None
        else {
            entry["parcel_ref"]: entry["neighborhood_aggregate"] and not entry["revocation_pending"]
            for entry in payload["sharing_settings"]
        }
    )
    cells = defaultdict(list)
    for contribution in payload["contributions"]:
        if contribution["source_class"] == "shared_data" and not eligibility.get(contribution["parcel_ref"], False):
            continue
        cells[contribution["cell_id"]].append(contribution)

    aggregated_cells = []
    for cell_id, contributions in sorted(cells.items()):
        shared = [item for item in contributions if item["source_class"] == "shared_data"]
        public = [item for item in contributions if item["source_class"] == "public_context"]
        shared_visible = len(shared) >= payload["min_participants"]
        provenance_classes = []
        if shared_visible:
            provenance_classes.append("shared_data")
        if public:
            provenance_classes.append("public_context")

        aggregated_cells.append(
            {
                "cell_id": cell_id,
                "shared_signal_status": "visible" if shared_visible else "suppressed",
                "shared_participant_count": len(shared) if shared_visible else None,
                "suppression_reason": None if shared_visible else "insufficient_participation",
                "shared_hazards": average_hazards(shared) if shared_visible else None,
                "public_context_hazards": average_hazards(public) if public else None,
                "max_delay_minutes": max(item["delayed_minutes"] for item in contributions),
                "provenance_classes": provenance_classes,
                "coverage_note": "Delayed, aggregated neighborhood-level conditions only.",
            }
        )

    return {
        "generated_at": payload["generated_at"],
        "min_participants": payload["min_participants"],
        "cells": aggregated_cells,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate shared neighborhood signals into a coarse shared-map view.")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "shared-neighborhood-signal.example.json"),
        help="Path to a shared-neighborhood-signal JSON file.",
    )
    parser.add_argument(
        "--sharing-store",
        default=None,
        help="Optional path to a JSON sharing store file used to determine neighborhood eligibility.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = load_json(Path(args.input).resolve())
        sharing_store = load_sharing_store(Path(args.sharing_store).resolve()) if args.sharing_store else None
        result = aggregate_shared_map(payload, sharing_store=sharing_store)
    except (SharedMapError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR shared map aggregation: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
