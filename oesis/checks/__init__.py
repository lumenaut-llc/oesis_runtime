"""Lane-aware acceptance helper exports."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane

from .v0_1.acceptance import build_v01_runtime_flow, verify_http_flow_artifacts, verify_runtime_flow_artifacts
from .v1_0.acceptance import build_v10_runtime_flow


def build_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    lane = resolve_runtime_lane()
    if lane == "v1.0":
        return build_v10_runtime_flow(computed_at=computed_at)
    return build_v01_runtime_flow(computed_at=computed_at)


__all__ = ["build_runtime_flow", "build_v01_runtime_flow", "build_v10_runtime_flow", "verify_http_flow_artifacts", "verify_runtime_flow_artifacts"]
