"""v0.3 acceptance helpers: flood-capable parcel kit (bench-air + mast-lite + flood-node)."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.context.v0_3.loader import load_default_bundle
from oesis.ingest.v0_3.normalize_packet import normalize_packet
from oesis.ingest.v0_3.normalize_flood_packet import normalize_flood_packet
from oesis.ingest.v0_3.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v0_3.normalize_public_weather_context import normalize_public_weather_context
from oesis.inference.v0_3.infer_parcel_state import combine_public_contexts, infer_parcel_state
from oesis.parcel_platform.v0_3.format_evidence_summary import build_evidence_summary
from oesis.parcel_platform.v0_3.format_parcel_view import build_parcel_view


def build_v03_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    bundle = load_default_bundle()
    normalized = normalize_packet(bundle["node_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.3")
    public_weather = normalize_public_weather_context(bundle["raw_public_weather"])
    public_smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
    public_context = combine_public_contexts([public_weather, public_smoke])
    parcel_state = infer_parcel_state(
        normalized,
        computed_at=computed_at,
        runtime_lane="v0.3",
        parcel_context=bundle["parcel_context"],
        public_context=public_context,
    )
    parcel_view = build_parcel_view(parcel_state)
    evidence_summary = build_evidence_summary(parcel_state)

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

    if "mast_lite_packet" in bundle:
        mast_lite_normalized = normalize_packet(
            bundle["mast_lite_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.3"
        )
        mast_lite_parcel_state = infer_parcel_state(
            mast_lite_normalized,
            computed_at=computed_at,
            runtime_lane="v0.3",
            parcel_context=bundle["parcel_context"],
            public_context=public_context,
        )
        result["mast_lite_packet"] = bundle["mast_lite_packet"]
        result["mast_lite_normalized"] = mast_lite_normalized
        result["mast_lite_parcel_state"] = mast_lite_parcel_state

    if "flood_packet" in bundle:
        flood_normalized = normalize_flood_packet(
            bundle["flood_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.3"
        )
        result["flood_packet"] = bundle["flood_packet"]
        result["flood_normalized"] = flood_normalized

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

    if "flood_normalized" in payload:
        flood = payload["flood_normalized"]
        if flood["node_id"] != "flood-node-01":
            raise SystemExit(f"flood normalized node_id mismatch: {flood['node_id']}")
        if flood["observation_type"] != "flood.low_point.snapshot":
            raise SystemExit(f"flood observation_type mismatch: {flood['observation_type']}")
        for key in ("node_id", "parcel_id", "values", "provenance"):
            if key not in flood:
                raise SystemExit(f"flood normalized observation missing {key}")
        flood_values = flood["values"]
        for key in ("water_depth_cm", "distance_cm", "dry_reference_distance_cm"):
            if key not in flood_values:
                raise SystemExit(f"flood values missing {key}")

    parcel_context = payload["parcel_context"]
    node_ids = [n["node_id"] for n in parcel_context.get("node_installations", [])]
    if "flood-node-01" not in node_ids:
        raise SystemExit("v0.3 parcel_context must include flood-node-01 in node_installations")


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


def verify_value_assertions(payload: dict) -> None:
    """Assert v0.3 inference values are in valid ranges including flood."""
    ps = payload["parcel_state"]

    # Confidence in [0, 1]
    conf = ps.get("confidence")
    if conf is None or not 0.0 <= conf <= 1.0:
        raise SystemExit(f"v0.3 confidence out of range: {conf}")

    # Status enums
    valid_statuses = {"safe", "watch", "warning", "danger", "unknown", "not_assessed"}
    for status_key in ("shelter_status", "reentry_status", "egress_status", "asset_risk_status"):
        val = ps.get(status_key)
        if val not in valid_statuses:
            raise SystemExit(f"v0.3 {status_key} invalid: {val}")

    # Hazard statuses including flood
    for haz_name, haz_status in ps.get("hazard_statuses", {}).items():
        if haz_status not in valid_statuses:
            raise SystemExit(f"v0.3 hazard_statuses.{haz_name} invalid: {haz_status}")

    # Flood normalized values must be physically reasonable
    if "flood_normalized" in payload:
        fv = payload["flood_normalized"]["values"]
        depth = fv.get("water_depth_cm")
        if depth is not None and depth < 0:
            raise SystemExit(f"v0.3 flood water_depth_cm negative: {depth}")
        dist = fv.get("distance_cm")
        if dist is not None and dist < 0:
            raise SystemExit(f"v0.3 flood distance_cm negative: {dist}")


def main() -> None:
    payload = build_v03_runtime_flow()
    verify_runtime_flow_artifacts(payload)
    verify_value_assertions(payload)
    expected_lane = "v0.3"
    active_lane = resolve_runtime_lane()
    if active_lane != expected_lane:
        raise SystemExit(f"expected runtime lane {expected_lane}, got {active_lane}")
    if "flood_normalized" not in payload:
        raise SystemExit("v0.3 acceptance requires flood normalized observation")
    flood = payload["flood_normalized"]
    if flood["observation_type"] != "flood.low_point.snapshot":
        raise SystemExit("flood observation_type must be flood.low_point.snapshot")
    node_count = len(payload["parcel_context"]["node_installations"])
    print(f"PASS oesis.checks v0.3 offline (flood-capable: {node_count} nodes)")


if __name__ == "__main__":
    main()
