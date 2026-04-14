"""Lane-aware inference package helpers."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

from oesis.common.runtime_lane import resolve_runtime_lane

_LANE_TO_PACKAGE = {
    "v0.1": "oesis.inference.v0_1",
    "v0.2": "oesis.inference.v0_2",
    "v0.3": "oesis.inference.v0_3",
    "v0.4": "oesis.inference.v0_4",
    "v0.5": "oesis.inference.v0_5",
    "v1.0": "oesis.inference.v1_0",
}


def lane_package_module(*, lane: str | None = None) -> ModuleType:
    resolved = resolve_runtime_lane(lane)
    return import_module(_LANE_TO_PACKAGE[resolved])


def lane_module(module_name: str, *, lane: str | None = None) -> ModuleType:
    resolved = resolve_runtime_lane(lane)
    return import_module(f"{_LANE_TO_PACKAGE[resolved]}.{module_name}")


__all__ = ["lane_module", "lane_package_module"]
