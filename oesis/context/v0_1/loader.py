"""Small context loader helpers for the narrow runtime path plus bridge support examples."""

from __future__ import annotations

import json
from pathlib import Path

from oesis.common.repo_paths import EXAMPLES_DIR

DEFAULT_PARCEL_ID = "parcel_demo_001"


def load_example_json(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def load_parcel_context(path: str | Path | None = None, *, parcel_id: str = DEFAULT_PARCEL_ID) -> dict:
    context = load_example_json("parcel-context.example.json") if path is None else json.loads(Path(path).resolve().read_text(encoding="utf-8"))
    context["parcel_id"] = parcel_id
    for installation in context.get("node_installations", []):
        installation.setdefault("node_id", "bench-air-01")
    return context


def load_public_contexts(
    weather_path: str | Path | None = None,
    smoke_path: str | Path | None = None,
) -> tuple[dict, dict]:
    weather = load_example_json("raw-public-weather.example.json") if weather_path is None else json.loads(Path(weather_path).resolve().read_text(encoding="utf-8"))
    smoke = load_example_json("raw-public-smoke.example.json") if smoke_path is None else json.loads(Path(smoke_path).resolve().read_text(encoding="utf-8"))
    return weather, smoke


def load_support_objects() -> dict:
    return {
        "house_state": load_example_json("house-state.example.json"),
        "house_capability": load_example_json("house-capability.example.json"),
        "equipment_state_observation": load_example_json("equipment-state-observation.example.json"),
        "source_provenance_record": load_example_json("source-provenance-record.example.json"),
        "control_compatibility": load_example_json("control-compatibility.example.json"),
        "intervention_event": load_example_json("intervention-event.example.json"),
        "verification_outcome": load_example_json("verification-outcome.example.json"),
    }


def load_default_bundle(*, parcel_id: str = DEFAULT_PARCEL_ID, include_support_objects: bool = False) -> dict:
    packet = load_example_json("node-observation.example.json")
    packet["node_id"] = "bench-air-01"
    parcel_context = load_parcel_context(parcel_id=parcel_id)
    raw_public_weather, raw_public_smoke = load_public_contexts()
    bundle = {
        "parcel_id": parcel_id,
        "node_packet": packet,
        "parcel_context": parcel_context,
        "raw_public_weather": raw_public_weather,
        "raw_public_smoke": raw_public_smoke,
    }
    if include_support_objects:
        support_objects = load_support_objects()
        support_objects["house_state"]["parcel_id"] = parcel_id
        support_objects["house_capability"]["parcel_id"] = parcel_id
        support_objects["equipment_state_observation"]["parcel_id"] = parcel_id
        support_objects["source_provenance_record"]["parcel_id"] = parcel_id
        support_objects["control_compatibility"]["parcel_id"] = parcel_id
        support_objects["intervention_event"]["parcel_id"] = parcel_id
        support_objects["verification_outcome"]["parcel_id"] = parcel_id
        bundle.update(support_objects)
    return bundle
