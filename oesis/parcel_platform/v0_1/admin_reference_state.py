#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from .serve_parcel_api import (
    append_access_event,
    export_bundle_for_parcel,
    list_rights_requests,
    load_sharing_store,
    process_delete_request,
    sharing_from_store,
    update_sharing_store,
)
from .summarize_reference_state import summarize


def cmd_summary(args: argparse.Namespace) -> int:
    sharing_store = load_sharing_store(Path(args.sharing_store).resolve())
    rights_store = json.loads(Path(args.rights_store).resolve().read_text(encoding="utf-8")) if Path(args.rights_store).resolve().exists() else {"updated_at": None, "requests": []}
    access_log = json.loads(Path(args.access_log).resolve().read_text(encoding="utf-8")) if Path(args.access_log).resolve().exists() else []
    print(json.dumps(summarize(sharing_store, rights_store, access_log), indent=2, sort_keys=True))
    return 0


def cmd_set_neighborhood_sharing(args: argparse.Namespace) -> int:
    store_path = Path(args.sharing_store).resolve()
    sharing = sharing_from_store(store_path, args.parcel_id)
    sharing["private_only"] = not args.enabled
    sharing["neighborhood_aggregate"] = args.enabled
    sharing["updated_at"] = args.updated_at or sharing["updated_at"]
    update_sharing_store(store_path, args.parcel_id, sharing)
    append_access_event(
        Path(args.access_log).resolve(),
        actor="admin-reference-cli",
        action="set_neighborhood_sharing",
        parcel_id=args.parcel_id,
        data_classes=["administrative_record"],
        justification="manual_reference_admin_update",
    )
    print(json.dumps(sharing_from_store(store_path, args.parcel_id), indent=2, sort_keys=True))
    return 0


def cmd_list_rights(args: argparse.Namespace) -> int:
    requests = list_rights_requests(Path(args.rights_store).resolve(), args.parcel_id)
    print(json.dumps(requests, indent=2, sort_keys=True))
    return 0


def cmd_export_access_log(args: argparse.Namespace) -> int:
    access_path = Path(args.access_log).resolve()
    events = json.loads(access_path.read_text(encoding="utf-8")) if access_path.exists() else []
    if args.parcel_id:
        events = [event for event in events if event["parcel_id"] == args.parcel_id]
    print(json.dumps(events, indent=2, sort_keys=True))
    return 0


def cmd_process_delete_request(args: argparse.Namespace) -> int:
    result = process_delete_request(
        Path(args.rights_store).resolve(),
        Path(args.sharing_store).resolve(),
        args.request_id,
    )
    append_access_event(
        Path(args.access_log).resolve(),
        actor="admin-reference-cli",
        action="process_delete_request",
        parcel_id=result["parcel_id"],
        data_classes=["administrative_record"],
        justification="manual_delete_request_execution",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_process_export_request(args: argparse.Namespace) -> int:
    from .serve_parcel_api import process_export_request

    result = process_export_request(
        Path(args.rights_store).resolve(),
        Path(args.sharing_store).resolve(),
        Path(args.access_log).resolve(),
        args.request_id,
        Path(args.output).resolve(),
    )
    append_access_event(
        Path(args.access_log).resolve(),
        actor="admin-reference-cli",
        action="process_export_request",
        parcel_id=result["parcel_id"],
        data_classes=["administrative_record"],
        justification="manual_export_request_execution",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Admin helper for inspecting and updating reference governance state.")
    parser.add_argument("--sharing-store", default="/tmp/oesis-sharing-store.json", help="Path to the JSON sharing store file.")
    parser.add_argument("--rights-store", default="/tmp/oesis-rights-request-store.json", help="Path to the JSON rights-request store file.")
    parser.add_argument("--access-log", default="/tmp/oesis-operator-access-log.json", help="Path to the JSON operator access log file.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="Show the current reference governance state summary.")
    summary.set_defaults(func=cmd_summary)

    set_sharing = subparsers.add_parser("set-neighborhood-sharing", help="Enable or disable neighborhood sharing for a parcel.")
    set_sharing.add_argument("parcel_id", help="Parcel identifier to update.")
    set_sharing.add_argument("--enabled", action="store_true", help="Enable neighborhood sharing. Omit to disable.")
    set_sharing.add_argument("--updated-at", default=None, help="Optional explicit timestamp for the sharing update.")
    set_sharing.set_defaults(func=cmd_set_neighborhood_sharing)

    list_rights = subparsers.add_parser("list-rights", help="List persisted rights requests for a parcel.")
    list_rights.add_argument("parcel_id", help="Parcel identifier to inspect.")
    list_rights.set_defaults(func=cmd_list_rights)

    export_access = subparsers.add_parser("export-access-log", help="Print access-log events, optionally filtered by parcel.")
    export_access.add_argument("--parcel-id", default=None, help="Optional parcel identifier filter.")
    export_access.set_defaults(func=cmd_export_access_log)

    process_delete = subparsers.add_parser("process-delete-request", help="Complete a delete request and remove parcel sharing state.")
    process_delete.add_argument("request_id", help="Delete request identifier to process.")
    process_delete.set_defaults(func=cmd_process_delete_request)

    process_export = subparsers.add_parser("process-export-request", help="Complete an export request and write a bundle file.")
    process_export.add_argument("request_id", help="Export request identifier to process.")
    process_export.add_argument("--output", required=True, help="Path to write the export bundle JSON.")
    process_export.set_defaults(func=cmd_process_export_request)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR admin reference state: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
