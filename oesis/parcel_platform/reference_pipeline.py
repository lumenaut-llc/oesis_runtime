#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys

from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.checks.v0_1.acceptance import build_v01_runtime_flow
from oesis.checks.v0_2.acceptance import build_v02_runtime_flow
from oesis.checks.v0_3.acceptance import build_v03_runtime_flow
from oesis.checks.v0_4.acceptance import build_v04_runtime_flow
from oesis.checks.v0_5.acceptance import build_v05_runtime_flow
from oesis.checks.v1_0.acceptance import build_v10_runtime_flow

_LANE_TO_FLOW = {
    "v0.1": build_v01_runtime_flow,
    "v0.2": build_v02_runtime_flow,
    "v0.3": build_v03_runtime_flow,
    "v0.4": build_v04_runtime_flow,
    "v0.5": build_v05_runtime_flow,
    "v1.0": build_v10_runtime_flow,
}


def build_pipeline(*, computed_at: str | None) -> dict:
    lane = resolve_runtime_lane()
    builder = _LANE_TO_FLOW.get(lane, build_v01_runtime_flow)
    return builder(computed_at=computed_at or "2026-03-30T19:46:00Z")


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
