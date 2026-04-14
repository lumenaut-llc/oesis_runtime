"""Lane-aware context loading helpers."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

from oesis.common.runtime_lane import resolve_runtime_lane

_LANE_TO_PACKAGE = {
    "v0.1": "oesis.context.v0_1",
    "v0.2": "oesis.context.v0_2",
    "v1.0": "oesis.context.v1_0",
}


def lane_package_module(*, lane: str | None = None) -> ModuleType:
    resolved = resolve_runtime_lane(lane)
    return import_module(_LANE_TO_PACKAGE[resolved])


def lane_loader_module(*, lane: str | None = None) -> ModuleType:
    resolved = resolve_runtime_lane(lane)
    return import_module(f"{_LANE_TO_PACKAGE[resolved]}.loader")


def load_default_bundle(*, parcel_id: str = "parcel_demo_001", lane: str | None = None) -> dict:
    return lane_loader_module(lane=lane).load_default_bundle(parcel_id=parcel_id)


def load_example_json(name: str, *, lane: str | None = None) -> dict:
    return lane_loader_module(lane=lane).load_example_json(name)


def load_parcel_context(path=None, *, parcel_id: str = "parcel_demo_001", lane: str | None = None) -> dict:
    return lane_loader_module(lane=lane).load_parcel_context(path=path, parcel_id=parcel_id)


def load_public_contexts(weather_path=None, smoke_path=None, *, lane: str | None = None) -> tuple[dict, dict]:
    return lane_loader_module(lane=lane).load_public_contexts(weather_path=weather_path, smoke_path=smoke_path)


DEFAULT_PARCEL_ID = "parcel_demo_001"

__all__ = ["DEFAULT_PARCEL_ID", "lane_loader_module", "lane_package_module", "load_default_bundle", "load_example_json", "load_parcel_context", "load_public_contexts"]
