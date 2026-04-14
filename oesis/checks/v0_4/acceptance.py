"""v0.4 acceptance helpers: multi-node registry + evidence composition."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.context.v0_4.loader import load_default_bundle
from oesis.ingest.v0_4.normalize_packet import normalize_packet
from oesis.ingest.v0_4.normalize_flood_packet import normalize_flood_packet
from oesis.ingest.v0_4.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v0_4.normalize_public_weather_context import normalize_public_weather_context
from oesis.ingest.v0_4.manage_node_registry import (
    filter_active_nodes,
    validate_node_lifecycle,
    bind_observation_to_registry,
)
from oesis.inference.v0_4.infer_parcel_state import (
    combine_public_contexts,
    compose_multi_node_evidence,
    infer_parcel_state,
)
from oesis.parcel_platform.v0_4.format_evidence_summary import build_evidence_summary
from oesis.parcel_platform.v0_4.format_parcel_view import build_parcel_view


def build_v04_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    bundle = load_default_bundle()
    registry = bundle.get("node_registry")

    # Normalize bench-air observation
    normalized = normalize_packet(bundle["node_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.4")
    if registry:
        validate_node_lifecycle(registry, normalized["node_id"])
        normalized = bind_observation_to_registry(normalized, registry)

    public_weather = normalize_public_weather_context(bundle["raw_public_weather"])
    public_smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
    public_context = combine_public_contexts([public_weather, public_smoke])
    parcel_state = infer_parcel_state(
        normalized,
        computed_at=computed_at,
        runtime_lane="v0.4",
        parcel_context=bundle["parcel_context"],
        public_context=public_context,
    )
    parcel_view = build_parcel_view(parcel_state)
    evidence_summary = build_evidence_summary(parcel_state)

    all_observations = [normalized]

    result = {
        "node_packet": bundle["node_packet"],
        "parcel_context": bundle["parcel_context"],
        "raw_public_weather": bundle["raw_public_weather"],
        "raw_public_smoke": bundle["raw_public_smoke"],
        "public_context": public_context,
        "normalized_observation": normalized,
        "parcel_state": parcel_state,
        "parcel_view": parcel_view,
        "evidence_summary": evidence_summary,
    }

    # Normalize mast-lite observation
    if "mast_lite_packet" in bundle:
        mast_lite_normalized = normalize_packet(
            bundle["mast_lite_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.4"
        )
        if registry:
            validate_node_lifecycle(registry, mast_lite_normalized["node_id"])
            mast_lite_normalized = bind_observation_to_registry(mast_lite_normalized, registry)
        mast_lite_parcel_state = infer_parcel_state(
            mast_lite_normalized,
            computed_at=computed_at,
            runtime_lane="v0.4",
            parcel_context=bundle["parcel_context"],
            public_context=public_context,
        )
        result["mast_lite_packet"] = bundle["mast_lite_packet"]
        result["mast_lite_normalized"] = mast_lite_normalized
        result["mast_lite_parcel_state"] = mast_lite_parcel_state
        all_observations.append(mast_lite_normalized)

    # Normalize flood observation
    if "flood_packet" in bundle:
        flood_normalized = normalize_flood_packet(
            bundle["flood_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.4"
        )
        if registry:
            validate_node_lifecycle(registry, flood_normalized["node_id"])
            flood_normalized = bind_observation_to_registry(flood_normalized, registry)
        result["flood_packet"] = bundle["flood_packet"]
        result["flood_normalized"] = flood_normalized
        all_observations.append(flood_normalized)

    # Compose multi-node evidence
    if registry:
        active_nodes = filter_active_nodes(registry)
        result["active_registry_nodes"] = active_nodes
    composed = compose_multi_node_evidence(all_observations, parcel_context=bundle["parcel_context"])
    result["multi_node_evidence"] = composed
    result["node_registry"] = registry

    return result


def verify_runtime_flow_artifacts(payload: dict) -> None:
    required_top = {
        "node_packet",
        "parcel_context",
        "normalized_observation",
        "parcel_state",
        "parcel_view",
        "evidence_summary",
    }
    missing = required_top - payload.keys()
    if missing:
        raise SystemExit(f"missing top-level keys: {sorted(missing)}")

    normalized = payload["normalized_observation"]
    parcel_state = payload["parcel_state"]
    parcel_view = payload["parcel_view"]

    for key in ("node_id", "parcel_id", "values", "provenance"):
        if key not in normalized:
            raise SystemExit(f"normalized observation missing {key}")
    if "versioning" not in normalized:
        raise SystemExit("normalized observation missing versioning")

    expected_lane = resolve_runtime_lane()
    for artifact_name, artifact in [("normalized_observation", normalized), ("parcel_state", parcel_state)]:
        lane_in_artifact = artifact.get("versioning", {}).get("runtime_lane")
        if lane_in_artifact != expected_lane:
            raise SystemExit(f"{artifact_name} lane mismatch: expected {expected_lane}, got {lane_in_artifact}")

    for key in ("shelter_status", "reentry_status", "egress_status", "asset_risk_status", "confidence", "evidence_mode", "reasons", "freshness", "provenance_summary"):
        if key not in parcel_state:
            raise SystemExit(f"parcel_state missing {key}")
    if "versioning" not in parcel_state:
        raise SystemExit("parcel_state missing versioning")

    for key in ("statuses", "summary", "confidence", "evidence_mode", "freshness", "provenance_summary"):
        if key not in parcel_view:
            raise SystemExit(f"parcel_view missing {key}")
    if "versioning" not in parcel_view:
        raise SystemExit("parcel_view missing versioning")
    parcel_view_lane = parcel_view.get("versioning", {}).get("runtime_lane")
    if parcel_view_lane != expected_lane:
        raise SystemExit(f"parcel_view lane mismatch: expected {expected_lane}, got {parcel_view_lane}")

    # v0.4-specific: multi-node evidence composition
    if "multi_node_evidence" not in payload:
        raise SystemExit("v0.4 acceptance requires multi_node_evidence")
    evidence = payload["multi_node_evidence"]
    if evidence["observation_count"] < 2:
        raise SystemExit(f"v0.4 requires multi-node evidence, got observation_count={evidence['observation_count']}")
    diversity = evidence["source_diversity"]
    if diversity["indoor_count"] < 1:
        raise SystemExit("v0.4 evidence must include indoor observations")
    if diversity["outdoor_count"] + diversity["sheltered_count"] < 1:
        raise SystemExit("v0.4 evidence must include outdoor or sheltered observations")

    # v0.4-specific: registry binding
    if "node_registry" in payload and payload["node_registry"]:
        registry_meta = normalized.get("provenance", {}).get("registry_metadata")
        if not registry_meta:
            raise SystemExit("v0.4 normalized observation should have registry_metadata in provenance")
        if "active_registry_nodes" in payload:
            active = payload["active_registry_nodes"]
            if len(active) < 2:
                raise SystemExit(f"v0.4 requires at least 2 active registry nodes, got {len(active)}")

    # flood checks from v0.3
    if "flood_normalized" in payload:
        flood = payload["flood_normalized"]
        if flood["observation_type"] != "flood.low_point.snapshot":
            raise SystemExit(f"flood observation_type mismatch: {flood['observation_type']}")
        flood_values = flood["values"]
        for key in ("water_depth_cm", "distance_cm", "dry_reference_distance_cm"):
            if key not in flood_values:
                raise SystemExit(f"flood values missing {key}")


def verify_http_flow_artifacts(*, ingest_health: dict, inference_health: dict, parcel_health: dict, ingest_payload: dict, inference_payload: dict, parcel_payload: dict) -> None:
    assert ingest_health["ok"] is True
    assert inference_health["ok"] is True
    assert parcel_health["ok"] is True

    normalized = ingest_payload["normalized_observation"]
    parcel_state = inference_payload["parcel_state"]
    parcel_view = parcel_payload["parcel_view"]

    for key in ("node_id", "parcel_id", "values", "provenance"):
        if key not in normalized:
            raise SystemExit(f"normalized observation missing {key}")
    if "versioning" not in normalized:
        raise SystemExit("normalized observation missing versioning")

    for key in ("shelter_status", "reentry_status", "egress_status", "asset_risk_status", "confidence", "evidence_mode", "reasons", "freshness", "provenance_summary"):
        if key not in parcel_state:
            raise SystemExit(f"parcel_state missing {key}")
    if "versioning" not in parcel_state:
        raise SystemExit("parcel_state missing versioning")

    for key in ("statuses", "summary", "confidence", "evidence_mode", "freshness", "provenance_summary"):
        if key not in parcel_view:
            raise SystemExit(f"parcel_view missing {key}")
    if "versioning" not in parcel_view:
        raise SystemExit("parcel_view missing versioning")


def main() -> None:
    payload = build_v04_runtime_flow()
    verify_runtime_flow_artifacts(payload)
    expected_lane = "v0.4"
    active_lane = resolve_runtime_lane()
    if active_lane != expected_lane:
        raise SystemExit(f"expected runtime lane {expected_lane}, got {active_lane}")
    evidence = payload["multi_node_evidence"]
    obs_count = evidence["observation_count"]
    active_count = len(payload.get("active_registry_nodes", []))
    print(f"PASS oesis.checks v0.4 offline (multi-node: {obs_count} observations, {active_count} active registry nodes)")


if __name__ == "__main__":
    main()
