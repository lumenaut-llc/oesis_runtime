"""Lane-aware acceptance helper exports."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane

from .v0_1.acceptance import build_v01_runtime_flow, verify_http_flow_artifacts, verify_runtime_flow_artifacts
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


def build_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    lane = resolve_runtime_lane()
    builder = _LANE_TO_FLOW.get(lane, build_v01_runtime_flow)
    return builder(computed_at=computed_at)


__all__ = ["build_runtime_flow", "build_v01_runtime_flow", "build_v02_runtime_flow", "build_v03_runtime_flow", "build_v04_runtime_flow", "build_v05_runtime_flow", "build_v10_runtime_flow", "verify_http_flow_artifacts", "verify_runtime_flow_artifacts"]
