#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from .serve_parcel_api import append_access_event, process_delete_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process reference rights requests for parcel-platform governance flows.")
    parser.add_argument("--sharing-store", default="/tmp/oesis-sharing-store.json", help="Path to the JSON sharing store file.")
    parser.add_argument("--rights-store", default="/tmp/oesis-rights-request-store.json", help="Path to the JSON rights-request store file.")
    parser.add_argument("--access-log", default="/tmp/oesis-operator-access-log.json", help="Path to the JSON operator access log file.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    process_delete = subparsers.add_parser("process-delete", help="Complete a delete request and remove parcel sharing state.")
    process_delete.add_argument("request_id", help="Delete request identifier to process.")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "process-delete":
            result = process_delete_request(
                Path(args.rights_store).resolve(),
                Path(args.sharing_store).resolve(),
                args.request_id,
            )
            append_access_event(
                Path(args.access_log).resolve(),
                actor="rights-request-processor",
                action="process_delete_request",
                parcel_id=result["parcel_id"],
                data_classes=["administrative_record"],
                justification="delete_request_execution",
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR process rights requests: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
