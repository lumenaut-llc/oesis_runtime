#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from .validate_examples import ValidationError


def iter_candidate_lines(text: str):
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if not line.startswith("{"):
            continue
        yield line


def extract_latest_packet(text: str) -> dict:
    latest_packet = None
    latest_error = None

    for line in iter_candidate_lines(text):
        try:
            latest_packet = json.loads(line)
            latest_error = None
        except json.JSONDecodeError as exc:
            latest_error = exc

    if latest_packet is None:
        if latest_error is not None:
            raise ValidationError(f"no valid JSON packet found: {latest_error}")
        raise ValidationError("no candidate JSON packet lines found")

    return latest_packet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract the newest JSON packet line from a mixed serial log."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Path to a serial log file, or '-' to read the log from stdin.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Path to write the extracted packet JSON, or '-' for stdout.",
    )
    return parser.parse_args()


def read_text(input_value: str) -> str:
    if input_value == "-":
        return sys.stdin.read()
    return Path(input_value).resolve().read_text(encoding="utf-8")


def write_packet(packet: dict, output_value: str):
    serialized = json.dumps(packet, indent=2, sort_keys=True)
    if output_value == "-":
        print(serialized)
        return
    Path(output_value).resolve().write_text(serialized + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    try:
        packet = extract_latest_packet(read_text(args.input))
        write_packet(packet, args.output)
    except (ValidationError, FileNotFoundError) as exc:
        print(f"ERROR {args.input}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
