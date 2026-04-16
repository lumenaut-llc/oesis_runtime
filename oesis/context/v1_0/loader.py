"""Small context loader helpers for the narrow runtime path plus bridge support examples.

Supports live public feeds when OESIS_AIRNOW_API_KEY is set (DA-5, V1-G4).
Falls back to fixture data when no API keys are configured.
"""

from __future__ import annotations

import json
import os
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


def load_public_contexts_live(parcel_id: str = DEFAULT_PARCEL_ID) -> tuple[dict, dict, str]:
    """Load public contexts from live feeds if configured, else from fixtures.

    Returns (weather_context, smoke_context, evidence_mode_hint) where
    evidence_mode_hint is one of:
    - "local_plus_public": fresh data from live feed
    - "degraded": stale cached data
    - "fixture": using checked-in fixture data (no API keys configured)
    """
    airnow_key = os.environ.get("OESIS_AIRNOW_API_KEY")
    if not airnow_key:
        weather, smoke = load_public_contexts()
        return weather, smoke, "fixture"

    # Lazy import to avoid import overhead when not using live feeds
    from oesis.context.public_feeds.public_feed_manager import PublicFeedManager

    manager = PublicFeedManager(airnow_api_key=airnow_key)

    # Try live smoke context
    smoke_ctx, smoke_mode = manager.get_smoke_context(parcel_id)

    # Weather: try live, fall back to fixture
    weather_ctx, weather_mode = manager.get_weather_context(parcel_id)
    if weather_ctx is None:
        weather_ctx = load_example_json("raw-public-weather.example.json")

    if smoke_ctx is None:
        smoke_ctx = load_example_json("raw-public-smoke.example.json")
        return weather_ctx, smoke_ctx, "fixture"

    # Use the worst mode between weather and smoke
    if smoke_mode == "degraded" or weather_mode == "degraded":
        return weather_ctx, smoke_ctx, "degraded"
    return weather_ctx, smoke_ctx, "local_plus_public"


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


def _try_load_example(name: str) -> dict | None:
    """Load an example JSON if present; return None if missing."""
    path = EXAMPLES_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def load_default_bundle(*, parcel_id: str = DEFAULT_PARCEL_ID) -> dict:
    packet = load_example_json("node-observation.example.json")
    packet["node_id"] = "bench-air-01"
    parcel_context = load_parcel_context(parcel_id=parcel_id)
    raw_public_weather, raw_public_smoke = load_public_contexts()
    support_objects = load_support_objects()
    support_objects["house_state"]["parcel_id"] = parcel_id
    support_objects["house_capability"]["parcel_id"] = parcel_id
    support_objects["equipment_state_observation"]["parcel_id"] = parcel_id
    support_objects["source_provenance_record"]["parcel_id"] = parcel_id
    support_objects["control_compatibility"]["parcel_id"] = parcel_id
    support_objects["intervention_event"]["parcel_id"] = parcel_id
    support_objects["verification_outcome"]["parcel_id"] = parcel_id

    result = {
        "parcel_id": parcel_id,
        "node_packet": packet,
        "parcel_context": parcel_context,
        "raw_public_weather": raw_public_weather,
        "raw_public_smoke": raw_public_smoke,
        **support_objects,
    }

    mast_lite = _try_load_example("node-observation-mast-lite.example.json")
    if mast_lite is not None:
        mast_lite["node_id"] = "mast-lite-01"
        result["mast_lite_packet"] = mast_lite

    flood = _try_load_example("node-observation-flood.example.json")
    if flood is not None:
        flood["node_id"] = "flood-node-01"
        result["flood_packet"] = flood

    return result
