"""Offline acceptance: build reference flow and verify artifact shapes."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane

from .v0_1.acceptance import build_v01_runtime_flow, verify_runtime_flow_artifacts
from .v0_2.acceptance import build_v02_runtime_flow
from .v0_3.acceptance import build_v03_runtime_flow
from .v0_4.acceptance import build_v04_runtime_flow
from .v0_5.acceptance import build_v05_runtime_flow
from .v1_0.acceptance import build_v10_runtime_flow

_LANE_TO_FLOW = {
    "v0.1": build_v01_runtime_flow,
    "v0.2": build_v02_runtime_flow,
    "v0.3": build_v03_runtime_flow,
    "v0.4": build_v04_runtime_flow,
    "v0.5": build_v05_runtime_flow,
    "v1.0": build_v10_runtime_flow,
}


def main() -> None:
    lane = resolve_runtime_lane()
    builder = _LANE_TO_FLOW.get(lane, build_v01_runtime_flow)
    payload = builder()
    verify_runtime_flow_artifacts(payload)
    print(f"PASS oesis.checks {payload['normalized_observation']['versioning']['runtime_lane']} offline")


if __name__ == "__main__":
    main()
