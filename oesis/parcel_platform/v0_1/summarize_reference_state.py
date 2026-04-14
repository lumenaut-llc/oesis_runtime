#!/usr/bin/env python3

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_optional_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(sharing_store: dict, rights_store: dict, access_log: list[dict]) -> dict:
    by_parcel = defaultdict(
        lambda: {
            "parcel_ref": None,
            "sharing": None,
            "rights_requests": [],
            "recent_access_events": [],
        }
    )

    for entry in sharing_store.get("parcels", []):
        parcel_id = entry["parcel_id"]
        by_parcel[parcel_id]["parcel_ref"] = entry["parcel_ref"]
        by_parcel[parcel_id]["sharing"] = entry["sharing"]

    for request in rights_store.get("requests", []):
        by_parcel[request["parcel_id"]]["rights_requests"].append(request)

    for event in access_log:
        by_parcel[event["parcel_id"]]["recent_access_events"].append(event)

    for parcel_id, summary in by_parcel.items():
        summary["rights_requests"] = sorted(summary["rights_requests"], key=lambda item: item["created_at"])
        summary["recent_access_events"] = sorted(summary["recent_access_events"], key=lambda item: item["occurred_at"])

    return {
        "parcel_count": len(by_parcel),
        "parcels": dict(sorted(by_parcel.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize file-backed reference governance state for parcel operations.")
    parser.add_argument(
        "--sharing-store",
        default="/tmp/oesis-sharing-store.json",
        help="Path to the JSON sharing store file.",
    )
    parser.add_argument(
        "--rights-store",
        default="/tmp/oesis-rights-request-store.json",
        help="Path to the JSON rights-request store file.",
    )
    parser.add_argument(
        "--access-log",
        default="/tmp/oesis-operator-access-log.json",
        help="Path to the JSON operator access log file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        sharing_store = load_optional_json(Path(args.sharing_store).resolve(), {"updated_at": None, "parcels": []})
        rights_store = load_optional_json(Path(args.rights_store).resolve(), {"updated_at": None, "requests": []})
        access_log = load_optional_json(Path(args.access_log).resolve(), [])
        summary = summarize(sharing_store, rights_store, access_log)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR summarize reference state: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
