#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from oesis.common.repo_paths import ASSETS_DIR

DEFAULT_GOVERNANCE_FIXTURES = [
    "consent-store.example.json",
    "sharing-store.example.json",
    "consent-record.example.json",
]


def canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check runtime governance example parity between lane and "
            "frozen baseline fixtures inside oesis-runtime."
        )
    )
    parser.add_argument(
        "--lane",
        default="v0.1",
        help="Runtime asset lane to compare (default: v0.1).",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=DEFAULT_GOVERNANCE_FIXTURES,
        help="Example filenames to compare.",
    )
    return parser.parse_args()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    baseline_examples_dir = ASSETS_DIR / "v0.1" / "examples"
    lane_examples_dir = ASSETS_DIR / args.lane / "examples"

    if not baseline_examples_dir.is_dir():
        print(f"ERROR missing baseline examples directory: {baseline_examples_dir}", file=sys.stderr)
        return 1
    if not lane_examples_dir.is_dir():
        print(f"ERROR missing lane examples directory: {lane_examples_dir}", file=sys.stderr)
        return 1

    failures = []
    for filename in args.files:
        baseline_path = baseline_examples_dir / filename
        lane_path = lane_examples_dir / filename
        if not baseline_path.exists():
            failures.append(f"FAIL {filename}: baseline fixture missing at {baseline_path}")
            continue
        if not lane_path.exists():
            failures.append(f"FAIL {filename}: lane fixture missing at {lane_path}")
            continue

        baseline_payload = load_json(baseline_path)
        lane_payload = load_json(lane_path)
        if canonical_json(baseline_payload) != canonical_json(lane_payload):
            failures.append(
                f"FAIL {filename}: payload mismatch between v0.1 baseline and {args.lane} lane"
            )
            continue
        print(f"PASS {filename}: v0.1 baseline == {args.lane} lane")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
