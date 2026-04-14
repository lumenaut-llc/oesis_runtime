"""Lane-aware common package helpers."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_LANE_TO_PACKAGE = {
    "v0.1": "oesis.common.v0_1",
    "v1.0": "oesis.common.v1_0",
}


def lane_module(module_name: str, *, lane: str = "v0.1") -> ModuleType:
    target = _LANE_TO_PACKAGE["v1.0" if lane == "v1.0" else "v0.1"]
    return import_module(f"{target}.{module_name}")


__all__ = ["lane_module"]
