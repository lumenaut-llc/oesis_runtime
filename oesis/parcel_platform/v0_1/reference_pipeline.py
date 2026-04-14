#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys

from oesis.checks.v0_1.acceptance import build_v01_runtime_flow


def build_pipeline(*, computed_at: str | None) -> dict:
    return build_v01_runtime_flow(computed_at=computed_at or "2026-03-30T19:46:00Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the reference OESIS pipeline from packet to parcel view."
    )
    parser.add_argument(
        "--computed-at",
        default="2026-03-30T19:46:00Z",
        help="Optional RFC 3339 timestamp passed to the inference stage.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = build_pipeline(computed_at=args.computed_at)
    except Exception as exc:
        print(f"ERROR reference pipeline: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
