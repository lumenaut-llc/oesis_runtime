"""Offline v0.1 acceptance: build reference flow and verify artifact shapes."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane

from .v0_1.acceptance import build_v01_runtime_flow, verify_runtime_flow_artifacts
from .v0_2.acceptance import build_v02_runtime_flow
from .v1_0.acceptance import build_v10_runtime_flow


def main() -> None:
    lane = resolve_runtime_lane()
    if lane == "v1.0":
        payload = build_v10_runtime_flow()
    elif lane == "v0.2":
        payload = build_v02_runtime_flow()
    else:
        payload = build_v01_runtime_flow()
    verify_runtime_flow_artifacts(payload)
    print(f"PASS oesis.checks {payload['normalized_observation']['versioning']['runtime_lane']} offline")


if __name__ == "__main__":
    main()
