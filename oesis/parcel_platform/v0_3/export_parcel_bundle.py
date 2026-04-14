#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from .serve_parcel_api import append_access_event, process_export_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process an export request and write a machine-readable parcel bundle.")
    parser.add_argument("request_id", help="Export request identifier to process.")
    parser.add_argument("--output", required=True, help="Path to write the export bundle JSON.")
    parser.add_argument("--sharing-store", default="/tmp/oesis-sharing-store.json", help="Path to the JSON sharing store file.")
    parser.add_argument("--rights-store", default="/tmp/oesis-rights-request-store.json", help="Path to the JSON rights-request store file.")
    parser.add_argument("--access-log", default="/tmp/oesis-operator-access-log.json", help="Path to the JSON operator access log file.")
    parser.add_argument("--parcel-state", default=None, help="Optional path to a parcel-state JSON file for the requested parcel.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = process_export_request(
            Path(args.rights_store).resolve(),
            Path(args.sharing_store).resolve(),
            Path(args.access_log).resolve(),
            args.request_id,
            Path(args.output).resolve(),
            parcel_state_path=Path(args.parcel_state).resolve() if args.parcel_state else None,
        )
        append_access_event(
            Path(args.access_log).resolve(),
            actor="export-bundle-processor",
            action="process_export_request",
            parcel_id=result["parcel_id"],
            data_classes=["administrative_record"],
            justification="export_request_execution",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR export parcel bundle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
