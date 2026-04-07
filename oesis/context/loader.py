"""Small context loader helpers for the v0.1 bench-air runtime path."""

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


def load_default_bundle(*, parcel_id: str = DEFAULT_PARCEL_ID) -> dict:
    packet = load_example_json("node-observation.example.json")
    packet["node_id"] = "bench-air-01"
    parcel_context = load_parcel_context(parcel_id=parcel_id)
    raw_public_weather, raw_public_smoke = load_public_contexts()
    return {
        "parcel_id": parcel_id,
        "node_packet": packet,
        "parcel_context": parcel_context,
        "raw_public_weather": raw_public_weather,
        "raw_public_smoke": raw_public_smoke,
    }
