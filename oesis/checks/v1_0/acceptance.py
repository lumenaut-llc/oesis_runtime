"""Offline v1.0 acceptance using the explicit opt-in runtime lane."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from oesis.common.repo_paths import EXAMPLES_DIR
from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.context.v1_0.loader import load_default_bundle
from oesis.ingest.v1_0.normalize_flood_packet import normalize_flood_packet
from oesis.ingest.v1_0.normalize_packet import normalize_packet
from oesis.ingest.v1_0.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v1_0.normalize_public_weather_context import normalize_public_weather_context
from oesis.inference.v1_0.infer_parcel_state import combine_public_contexts, infer_parcel_state
from oesis.parcel_platform.v1_0 import serve_parcel_api as parcel_api
from oesis.parcel_platform.v1_0.format_evidence_summary import build_evidence_summary
from oesis.parcel_platform.v1_0.format_parcel_view import build_parcel_view
from oesis.shared_map.v1_0.aggregate_shared_map import aggregate_shared_map

from oesis.checks.v0_1.acceptance import (
    verify_http_flow_artifacts,
    verify_runtime_flow_artifacts,
)


def build_v10_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    bundle = load_default_bundle()
    normalized = normalize_packet(bundle["node_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v1.0")
    public_weather = normalize_public_weather_context(bundle["raw_public_weather"])
    public_smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
    public_context = combine_public_contexts([public_weather, public_smoke])
    parcel_state = infer_parcel_state(
        normalized,
        computed_at=computed_at,
        runtime_lane="v1.0",
        parcel_context=bundle["parcel_context"],
        house_state=bundle["house_state"],
        house_capability=bundle["house_capability"],
        equipment_state_observation=bundle["equipment_state_observation"],
        source_provenance_record=bundle["source_provenance_record"],
        intervention_event=bundle["intervention_event"],
        verification_outcome=bundle["verification_outcome"],
        public_context=public_context,
    )
    parcel_view = build_parcel_view(parcel_state)
    evidence_summary = build_evidence_summary(parcel_state)
    result = {
        "node_packet": bundle["node_packet"],
        "parcel_context": bundle["parcel_context"],
        "house_state": bundle["house_state"],
        "house_capability": bundle["house_capability"],
        "equipment_state_observation": bundle["equipment_state_observation"],
        "source_provenance_record": bundle["source_provenance_record"],
        "control_compatibility": bundle["control_compatibility"],
        "intervention_event": bundle["intervention_event"],
        "verification_outcome": bundle["verification_outcome"],
        "raw_public_weather": bundle["raw_public_weather"],
        "raw_public_smoke": bundle["raw_public_smoke"],
        "public_context": public_context,
        "normalized_observation": normalized,
        "parcel_state": parcel_state,
        "parcel_view": parcel_view,
        "evidence_summary": evidence_summary,
    }

    # Mast-lite (sheltered outdoor) — uses shared bench-air normalizer
    if "mast_lite_packet" in bundle:
        mast_lite_normalized = normalize_packet(
            bundle["mast_lite_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v1.0"
        )
        mast_lite_parcel_state = infer_parcel_state(
            mast_lite_normalized,
            computed_at=computed_at,
            runtime_lane="v1.0",
            parcel_context=bundle["parcel_context"],
            public_context=public_context,
        )
        result["mast_lite_packet"] = bundle["mast_lite_packet"]
        result["mast_lite_normalized"] = mast_lite_normalized
        result["mast_lite_parcel_state"] = mast_lite_parcel_state

    # Flood node — uses dedicated flood normalizer
    if "flood_packet" in bundle:
        flood_normalized = normalize_flood_packet(
            bundle["flood_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v1.0"
        )
        result["flood_packet"] = bundle["flood_packet"]
        result["flood_normalized"] = flood_normalized

    return result


def verify_governance_runtime_behavior() -> None:
    with tempfile.TemporaryDirectory(prefix="oesis-v10-governance-") as temp_dir:
        consent_path = Path(temp_dir) / "consent-store.json"
        consent_path.write_text(
            json.dumps(deepcopy(parcel_api.DEFAULT_CONSENT_STORE), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        try:
            parcel_api.grant_consent(
                consent_path,
                parcel_id="parcel_001",
                payload={
                    "sharing_scope": "neighborhood_pm25",
                    "data_classes": ["indoor_pm25"],
                    "custody_tier": "shared",
                    "recipient_type": "neighborhood_pool",
                },
            )
        except parcel_api.ParcelViewError:
            pass
        else:
            raise SystemExit("expected structurally private data class to fail consent grant")

        granted = parcel_api.grant_consent(
            consent_path,
            parcel_id="parcel_001",
            payload={
                "sharing_scope": "neighborhood_pm25",
                "data_classes": ["outdoor_pm25"],
                "custody_tier": "shared",
                "recipient_type": "neighborhood_pool",
                "temporal_resolution": "hourly",
                "spatial_precision": "parcel",
            },
        )
        if granted["revoked_at"] is not None:
            raise SystemExit("newly granted consent should be active")

        status = parcel_api.governance_sharing_status(consent_path, "parcel_001")
        if not any(item["consent_id"] == granted["consent_id"] for item in status["currently_sharing"]):
            raise SystemExit("governance status missing newly granted consent")

        private_summary = parcel_api.governance_private_summary(consent_path, "parcel_001")
        if "indoor_pm25" not in private_summary["always_private"]:
            raise SystemExit("governance private summary missing structurally private class")

        revoked = parcel_api.revoke_consent(
            consent_path,
            parcel_id="parcel_001",
            consent_id=granted["consent_id"],
            reason="acceptance_test",
        )
        if revoked["revoked_at"] is None:
            raise SystemExit("revoked consent must carry revoked_at timestamp")

        history = parcel_api.governance_consent_history(consent_path, "parcel_001")
        if not any(item["consent_id"] == granted["consent_id"] and item["status"] == "revoked" for item in history):
            raise SystemExit("governance history missing revoked consent lifecycle state")

        shared_payload = json.loads((EXAMPLES_DIR / "shared-neighborhood-signal.example.json").read_text(encoding="utf-8"))
        consent_gated = aggregate_shared_map(shared_payload, consent_store=deepcopy(parcel_api.DEFAULT_CONSENT_STORE))
        by_cell = {entry["cell_id"]: entry for entry in consent_gated["cells"]}

        if "cell_demo_001" not in by_cell:
            raise SystemExit("expected shared-map output for cell_demo_001")
        if by_cell["cell_demo_001"]["shared_signal_status"] != "suppressed":
            raise SystemExit("expected cell_demo_001 shared signal to be suppressed under consent gating")
        if "cell_demo_002" in by_cell:
            raise SystemExit("revoked consent parcel contribution should not appear in shared-map output")


def verify_trust_score(payload: dict) -> None:
    """Verify the trust score is present and structurally valid."""
    ps = payload["parcel_state"]
    if "trust_score" not in ps:
        raise SystemExit("parcel_state missing trust_score")

    ts = ps["trust_score"]
    for key in ("parcel_id", "scored_at", "overall_band", "overall_score", "factors", "penalty_log"):
        if key not in ts:
            raise SystemExit(f"trust_score missing required field: {key}")

    if not isinstance(ts["overall_score"], (int, float)):
        raise SystemExit("trust_score overall_score must be numeric")
    if not 0.0 <= ts["overall_score"] <= 1.0:
        raise SystemExit(f"trust_score overall_score out of range: {ts['overall_score']}")
    if ts["overall_band"] not in ("high", "medium", "low", "degraded"):
        raise SystemExit(f"trust_score overall_band invalid: {ts['overall_band']}")

    expected_factors = {"freshness", "node_health", "calibration_state", "install_quality", "source_diversity"}
    actual_factors = {f["factor_key"] for f in ts["factors"]}
    if actual_factors != expected_factors:
        raise SystemExit(f"trust_score factors mismatch: expected {expected_factors}, got {actual_factors}")

    for factor in ts["factors"]:
        for fkey in ("factor_key", "weight", "score", "band", "reason"):
            if fkey not in factor:
                raise SystemExit(f"trust_score factor missing field: {fkey}")
        if not 0.0 <= factor["score"] <= 1.0:
            raise SystemExit(f"trust_score factor {factor['factor_key']} score out of range: {factor['score']}")
        if factor["band"] not in ("high", "medium", "low", "degraded"):
            raise SystemExit(f"trust_score factor {factor['factor_key']} band invalid: {factor['band']}")


def verify_value_assertions(payload: dict) -> None:
    """Assert inference values are in valid ranges and structurally correct."""
    ps = payload["parcel_state"]

    # Confidence must be in [0, 1]
    conf = ps.get("confidence")
    if conf is None or not 0.0 <= conf <= 1.0:
        raise SystemExit(f"confidence out of range: {conf}")

    # Status enums
    valid_statuses = {"safe", "watch", "warning", "danger", "unknown", "not_assessed"}
    for status_key in ("shelter_status", "reentry_status", "egress_status", "asset_risk_status"):
        val = ps.get(status_key)
        if val not in valid_statuses:
            raise SystemExit(f"{status_key} has invalid value: {val}")

    # Evidence mode
    valid_modes = {"local_only", "local_plus_public", "public_only", "local_plus_shared",
                   "local_plus_public_plus_shared", "degraded"}
    if ps.get("evidence_mode") not in valid_modes:
        raise SystemExit(f"evidence_mode invalid: {ps.get('evidence_mode')}")

    # Hazard probabilities in [0, 1]
    hazards = ps.get("hazards", {})
    for haz_key, haz_val in hazards.items():
        if isinstance(haz_val, dict):
            prob = haz_val.get("probability")
            if prob is not None and not 0.0 <= prob <= 1.0:
                raise SystemExit(f"hazard {haz_key} probability out of range: {prob}")

    # Hazard statuses
    for haz_name, haz_status in ps.get("hazard_statuses", {}).items():
        if haz_status not in valid_statuses:
            raise SystemExit(f"hazard_statuses.{haz_name} invalid: {haz_status}")

    # Freshness seconds must be non-negative
    freshness = ps.get("freshness", {})
    secs = freshness.get("seconds_since_latest")
    if secs is not None and secs < 0:
        raise SystemExit(f"freshness seconds_since_latest negative: {secs}")


def main() -> None:
    payload = build_v10_runtime_flow()
    verify_runtime_flow_artifacts(payload)
    verify_trust_score(payload)
    verify_value_assertions(payload)
    # Mast-lite assertions
    if "mast_lite_normalized" not in payload:
        raise SystemExit("v1.0 acceptance: mast_lite_normalized missing from flow")
    if payload["mast_lite_normalized"]["node_id"] != "mast-lite-01":
        raise SystemExit("mast_lite_normalized node_id mismatch")
    if "mast_lite_parcel_state" not in payload:
        raise SystemExit("v1.0 acceptance: mast_lite_parcel_state missing from flow")

    # Flood assertions
    if "flood_normalized" not in payload:
        raise SystemExit("v1.0 acceptance: flood_normalized missing from flow")
    if payload["flood_normalized"].get("observation_type") != "flood.low_point.snapshot":
        raise SystemExit(f"flood observation_type mismatch: {payload['flood_normalized'].get('observation_type')}")
    flood_values = payload["flood_normalized"].get("values", {})
    for flood_key in ("water_depth_cm", "distance_cm", "dry_reference_distance_cm"):
        val = flood_values.get(flood_key)
        if val is None or val < 0:
            raise SystemExit(f"flood values.{flood_key} invalid: {val}")

    verify_governance_runtime_behavior()
    expected_lane = "v1.0"
    active_lane = resolve_runtime_lane()
    if active_lane != expected_lane:
        raise SystemExit(f"expected runtime lane {expected_lane}, got {active_lane}")
    if payload["normalized_observation"]["versioning"]["runtime_lane"] != expected_lane:
        raise SystemExit("normalized observation lane mismatch")
    if payload["parcel_state"]["versioning"]["runtime_lane"] != expected_lane:
        raise SystemExit("parcel_state lane mismatch")
    if payload["parcel_view"]["versioning"]["runtime_lane"] != expected_lane:
        raise SystemExit("parcel_view lane mismatch")
    print("PASS oesis.checks v1.0 offline")


if __name__ == "__main__":
    main()
