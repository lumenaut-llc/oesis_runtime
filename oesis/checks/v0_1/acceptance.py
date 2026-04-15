"""v0.1 acceptance helpers for one parcel, one bench-air node."""

from __future__ import annotations

from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.context.v0_1.loader import load_default_bundle
from oesis.ingest.v0_1.normalize_packet import normalize_packet
from oesis.ingest.v0_1.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v0_1.normalize_public_weather_context import normalize_public_weather_context
from oesis.inference.v0_1.infer_parcel_state import combine_public_contexts, infer_parcel_state
from oesis.parcel_platform.v0_1.format_evidence_summary import build_evidence_summary
from oesis.parcel_platform.v0_1.format_parcel_view import build_parcel_view


def build_v01_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    bundle = load_default_bundle()
    normalized = normalize_packet(bundle["node_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.1")
    public_weather = normalize_public_weather_context(bundle["raw_public_weather"])
    public_smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
    public_context = combine_public_contexts([public_weather, public_smoke])
    parcel_state = infer_parcel_state(
        normalized,
        computed_at=computed_at,
        runtime_lane="v0.1",
        parcel_context=bundle["parcel_context"],
        public_context=public_context,
    )
    parcel_view = build_parcel_view(parcel_state)
    evidence_summary = build_evidence_summary(parcel_state)
    return {
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


def verify_value_assertions(payload: dict) -> None:
    """Assert inference values are in valid ranges (beyond structural checks)."""
    ps = payload["parcel_state"]

    # Confidence must be in [0, 1]
    conf = ps.get("confidence")
    if conf is None or not 0.0 <= conf <= 1.0:
        raise SystemExit(f"v0.1 confidence out of range: {conf}")

    # Status enums must be valid
    valid_statuses = {"safe", "watch", "warning", "danger", "unknown", "not_assessed"}
    for status_key in ("shelter_status", "reentry_status", "egress_status", "asset_risk_status"):
        val = ps.get(status_key)
        if val not in valid_statuses:
            raise SystemExit(f"v0.1 {status_key} has invalid value: {val}")

    # Evidence mode must be valid
    valid_modes = {"local_only", "local_plus_public", "public_only", "local_plus_shared",
                   "local_plus_public_plus_shared", "degraded"}
    if ps.get("evidence_mode") not in valid_modes:
        raise SystemExit(f"v0.1 evidence_mode invalid: {ps.get('evidence_mode')}")

    # Hazard probabilities in [0, 1]
    hazards = ps.get("hazards", {})
    for haz_key, haz_val in hazards.items():
        if isinstance(haz_val, dict):
            prob = haz_val.get("probability")
            if prob is not None and not 0.0 <= prob <= 1.0:
                raise SystemExit(f"v0.1 hazard {haz_key} probability out of range: {prob}")

    # Hazard statuses must be valid
    for haz_name, haz_status in ps.get("hazard_statuses", {}).items():
        if haz_status not in valid_statuses:
            raise SystemExit(f"v0.1 hazard_statuses.{haz_name} invalid: {haz_status}")

    # Freshness seconds must be non-negative
    freshness = ps.get("freshness", {})
    secs = freshness.get("seconds_since_latest")
    if secs is not None and secs < 0:
        raise SystemExit(f"v0.1 freshness seconds_since_latest negative: {secs}")

    # Provenance summary must have at least one source mode
    prov = ps.get("provenance_summary", {})
    if not prov.get("source_modes"):
        raise SystemExit("v0.1 provenance_summary missing source_modes")


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
