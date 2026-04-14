#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_optional_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def cleanup_access_log(access_log: list[dict], *, cutoff: datetime) -> tuple[list[dict], int]:
    kept = []
    removed = 0
    for event in access_log:
        occurred_at = parse_time(event["occurred_at"])
        if occurred_at < cutoff:
            removed += 1
            continue
        kept.append(event)
    return kept, removed


def cleanup_rights_store(store: dict, *, cutoff: datetime) -> tuple[dict, int]:
    kept = []
    removed = 0
    for request in store.get("requests", []):
        created_at = parse_time(request["created_at"])
        removable = request["status"] == "completed" and request["request_type"] == "export"
        if removable and created_at < cutoff:
            removed += 1
            continue
        kept.append(request)
    store["requests"] = kept
    return store, removed


def run_cleanup(*, rights_store_path: Path, access_log_path: Path, retention_days: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    rights_store = load_optional_json(rights_store_path, {"updated_at": None, "requests": []})
    access_log = load_optional_json(access_log_path, [])

    cleaned_access, access_removed = cleanup_access_log(access_log, cutoff=cutoff)
    cleaned_rights, rights_removed = cleanup_rights_store(rights_store, cutoff=cutoff)

    cleaned_rights["updated_at"] = now_iso()
    save_json(rights_store_path, cleaned_rights)
    save_json(access_log_path, cleaned_access)

    return {
        "ran_at": now_iso(),
        "access_events_removed": access_removed,
        "rights_requests_removed": rights_removed,
        "notes": [
            "Completed export requests older than the retention window were removed.",
            "Access events older than the retention window were removed.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run conservative retention cleanup for reference governance stores.")
    parser.add_argument("--rights-store", default="/tmp/oesis-rights-request-store.json", help="Path to the JSON rights-request store file.")
    parser.add_argument("--access-log", default="/tmp/oesis-operator-access-log.json", help="Path to the JSON operator access log file.")
    parser.add_argument("--retention-days", type=int, default=30, help="Retention window in days for pruneable reference records.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_cleanup(
            rights_store_path=Path(args.rights_store).resolve(),
            access_log_path=Path(args.access_log).resolve(),
            retention_days=args.retention_days,
        )
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR run retention cleanup: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
