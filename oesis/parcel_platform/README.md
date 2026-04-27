# oesis.parcel_platform

Output formatting + APIs. Builds parcel views, evidence summaries, and admin/governance surfaces from derived parcel state.

## Module shape

This module does NOT use per-version subdirectories. All formatters and API handlers live at the top level. Lane-aware behavior is parameterized via `runtime_lane` per call.

Files:

- `format_parcel_view.py` — main parcel-view renderer
- `format_evidence_summary.py` — evidence summary builder
- `serve_parcel_api.py` — HTTP API boundary
- `export_parcel_bundle.py` — export-bundle generator (v0.5 governance)
- `process_rights_requests.py` — rights-request lifecycle (v0.5 governance)
- `run_retention_cleanup.py` — retention-cleanup utility (v0.5 governance)
- `admin_reference_state.py` — admin reference flow
- `reference_pipeline.py` — end-to-end reference pipeline

## v1.5 bridge-object endpoints

The v1.5 contracts define six bridge support objects: `house-state`, `house-capability`, `intervention-event`, `verification-outcome`, `equipment-state-observation`, `source-provenance-record`. These have schema definitions and example payloads but **no standalone `/v1/<object>` endpoints in this module yet**.

The `infer_parcel_state` pipeline already CONSUMES these objects as inputs (via fixture loading), but operators cannot CREATE/UPDATE them at runtime. That's the gap.

Tracked as [oesis-program-specs U7 #116](https://github.com/lumenaut-llc/oesis-program-specs/issues/116) — six child tickets for the six endpoints. If you're exploring the tree and wondering whether v1.5 endpoint code was lost: it was never written.
