"""v0.5 acceptance helpers: governance enforcement (consent, retention, export, revocation)."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oesis.common.repo_paths import EXAMPLES_DIR
from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.context.v0_5.loader import load_default_bundle
from oesis.ingest.v0_5.normalize_packet import normalize_packet
from oesis.ingest.v0_5.normalize_flood_packet import normalize_flood_packet
from oesis.ingest.v0_5.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v0_5.normalize_public_weather_context import normalize_public_weather_context
from oesis.ingest.v0_5.manage_node_registry import (
    filter_active_nodes,
    validate_node_lifecycle,
    bind_observation_to_registry,
)
from oesis.inference.v0_5.infer_parcel_state import (
    combine_public_contexts,
    compose_multi_node_evidence,
    infer_parcel_state,
)
from oesis.parcel_platform.v0_5.format_evidence_summary import build_evidence_summary
from oesis.parcel_platform.v0_5.format_parcel_view import build_parcel_view
from oesis.parcel_platform.v0_5 import serve_parcel_api as parcel_api
from oesis.parcel_platform.v0_5.run_retention_cleanup import cleanup_access_log, cleanup_rights_store
from oesis.shared_map.v0_5.aggregate_shared_map import aggregate_shared_map


def build_v05_runtime_flow(*, computed_at: str = "2026-03-30T19:46:00Z") -> dict:
    bundle = load_default_bundle()
    registry = bundle.get("node_registry")

    normalized = normalize_packet(bundle["node_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.5")
    if registry:
        validate_node_lifecycle(registry, normalized["node_id"])
        normalized = bind_observation_to_registry(normalized, registry)

    public_weather = normalize_public_weather_context(bundle["raw_public_weather"])
    public_smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
    public_context = combine_public_contexts([public_weather, public_smoke])
    parcel_state = infer_parcel_state(
        normalized,
        computed_at=computed_at,
        runtime_lane="v0.5",
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

    if "mast_lite_packet" in bundle:
        mast_lite_normalized = normalize_packet(
            bundle["mast_lite_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.5"
        )
        if registry:
            validate_node_lifecycle(registry, mast_lite_normalized["node_id"])
            mast_lite_normalized = bind_observation_to_registry(mast_lite_normalized, registry)
        mast_lite_parcel_state = infer_parcel_state(
            mast_lite_normalized,
            computed_at=computed_at,
            runtime_lane="v0.5",
            parcel_context=bundle["parcel_context"],
            public_context=public_context,
        )
        result["mast_lite_packet"] = bundle["mast_lite_packet"]
        result["mast_lite_normalized"] = mast_lite_normalized
        result["mast_lite_parcel_state"] = mast_lite_parcel_state
        all_observations.append(mast_lite_normalized)

    if "flood_packet" in bundle:
        flood_normalized = normalize_flood_packet(
            bundle["flood_packet"], parcel_id=bundle["parcel_id"], runtime_lane="v0.5"
        )
        if registry:
            validate_node_lifecycle(registry, flood_normalized["node_id"])
            flood_normalized = bind_observation_to_registry(flood_normalized, registry)
        result["flood_packet"] = bundle["flood_packet"]
        result["flood_normalized"] = flood_normalized
        all_observations.append(flood_normalized)

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


def verify_governance_runtime_behavior() -> None:
    """Exercise consent lifecycle, retention cleanup, export bundle, and revocation suppression."""
    with tempfile.TemporaryDirectory(prefix="oesis-v05-governance-") as temp_dir:
        consent_path = Path(temp_dir) / "consent-store.json"
        consent_path.write_text(
            json.dumps(deepcopy(parcel_api.DEFAULT_CONSENT_STORE), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Consent lifecycle: grant should reject structurally private data
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

        # Consent lifecycle: grant valid consent
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

        # Consent status
        status = parcel_api.governance_sharing_status(consent_path, "parcel_001")
        if not any(item["consent_id"] == granted["consent_id"] for item in status["currently_sharing"]):
            raise SystemExit("governance status missing newly granted consent")

        # Private summary
        private_summary = parcel_api.governance_private_summary(consent_path, "parcel_001")
        if "indoor_pm25" not in private_summary["always_private"]:
            raise SystemExit("governance private summary missing structurally private class")

        # Revocation
        revoked = parcel_api.revoke_consent(
            consent_path,
            parcel_id="parcel_001",
            consent_id=granted["consent_id"],
            reason="acceptance_test",
        )
        if revoked["revoked_at"] is None:
            raise SystemExit("revoked consent must carry revoked_at timestamp")

        # Consent history
        history = parcel_api.governance_consent_history(consent_path, "parcel_001")
        if not any(item["consent_id"] == granted["consent_id"] and item["status"] == "revoked" for item in history):
            raise SystemExit("governance history missing revoked consent lifecycle state")

        # Revocation suppression in shared map
        shared_payload = json.loads((EXAMPLES_DIR / "shared-neighborhood-signal.example.json").read_text(encoding="utf-8"))
        consent_gated = aggregate_shared_map(shared_payload, consent_store=deepcopy(parcel_api.DEFAULT_CONSENT_STORE))
        by_cell = {entry["cell_id"]: entry for entry in consent_gated["cells"]}
        if "cell_demo_001" not in by_cell:
            raise SystemExit("expected shared-map output for cell_demo_001")
        if by_cell["cell_demo_001"]["shared_signal_status"] != "suppressed":
            raise SystemExit("expected cell_demo_001 shared signal to be suppressed under consent gating")


def verify_retention_enforcement() -> None:
    """Run retention cleanup and verify old records are pruned."""
    now = datetime.now(timezone.utc)
    old_timestamp = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent_timestamp = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    access_log = [
        {"occurred_at": old_timestamp, "action": "read", "actor": "system"},
        {"occurred_at": recent_timestamp, "action": "read", "actor": "system"},
    ]
    cutoff = now - timedelta(days=365)
    cleaned, removed = cleanup_access_log(access_log, cutoff=cutoff)
    if removed < 1:
        raise SystemExit("retention cleanup should have removed at least one old access log entry")
    if len(cleaned) != 1:
        raise SystemExit(f"retention cleanup should leave 1 recent entry, got {len(cleaned)}")

    rights_store = {
        "updated_at": recent_timestamp,
        "requests": [
            {"request_id": "old_req", "created_at": old_timestamp, "status": "completed", "request_type": "export", "parcel_id": "p1"},
            {"request_id": "new_req", "created_at": recent_timestamp, "status": "pending", "request_type": "export", "parcel_id": "p1"},
        ],
    }
    cleaned_store, rights_removed = cleanup_rights_store(rights_store, cutoff=cutoff)
    if rights_removed < 1:
        raise SystemExit("retention cleanup should have removed at least one old rights request")


def verify_export_enforcement() -> None:
    """Exercise export bundle and verify it produces output."""
    with tempfile.TemporaryDirectory(prefix="oesis-v05-export-") as temp_dir:
        td = Path(temp_dir)
        sharing_path = td / "sharing-store.json"
        rights_path = td / "rights-store.json"
        access_log_path = td / "access-log.json"

        sharing_path.write_text(json.dumps({"updated_at": "2026-04-01T00:00:00Z", "parcels": []}), encoding="utf-8")
        rights_path.write_text(json.dumps({"updated_at": "2026-04-01T00:00:00Z", "requests": []}), encoding="utf-8")
        access_log_path.write_text(json.dumps([]), encoding="utf-8")

        export = parcel_api.export_bundle_for_parcel(
            "parcel_001",
            sharing_store_path=sharing_path,
            rights_store_path=rights_path,
            access_log_path=access_log_path,
        )
        if "parcel_id" not in export:
            raise SystemExit("export bundle missing parcel_id")
        if "generated_at" not in export:
            raise SystemExit("export bundle missing generated_at")


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
    payload = build_v05_runtime_flow()
    verify_runtime_flow_artifacts(payload)
    verify_governance_runtime_behavior()
    verify_retention_enforcement()
    verify_export_enforcement()
    expected_lane = "v0.5"
    active_lane = resolve_runtime_lane()
    if active_lane != expected_lane:
        raise SystemExit(f"expected runtime lane {expected_lane}, got {active_lane}")
    evidence = payload.get("multi_node_evidence", {})
    obs_count = evidence.get("observation_count", 0)
    print(f"PASS oesis.checks v0.5 offline (governance: consent + retention + export + revocation, {obs_count} observations)")


if __name__ == "__main__":
    main()
