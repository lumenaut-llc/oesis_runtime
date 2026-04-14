#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from .normalize_packet import normalize_packet
from .validate_examples import ValidationError, load_json


def load_packet(input_value: str) -> dict:
    if input_value == "-":
        try:
            return json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            raise ValidationError(f"stdin: invalid JSON: {exc}") from exc

    return load_json(Path(input_value).resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and normalize a bench-air node packet from a file or stdin."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Path to a node packet JSON file, or '-' to read JSON from stdin.",
    )
    parser.add_argument(
        "--parcel-id",
        default="parcel_demo_001",
        help="Optional parcel identifier to attach to the normalized observation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        payload = load_packet(args.input)
        normalized = normalize_packet(payload, parcel_id=args.parcel_id)
    except (ValidationError, FileNotFoundError, KeyError) as exc:
        print(f"ERROR {args.input}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(normalized, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
