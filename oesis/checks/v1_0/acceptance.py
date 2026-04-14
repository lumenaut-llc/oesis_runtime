"""Offline v1.0 acceptance using the explicit opt-in runtime lane."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from oesis.common.repo_paths import EXAMPLES_DIR
from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.context.v1_0.loader import load_default_bundle
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
    return {
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


def main() -> None:
    payload = build_v10_runtime_flow()
    verify_runtime_flow_artifacts(payload)
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
