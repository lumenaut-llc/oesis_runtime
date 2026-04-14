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
