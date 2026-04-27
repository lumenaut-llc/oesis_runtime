# oesis.inference

Hazard assessment engine. Combines normalized observations + parcel context + public context into derived parcel state (smoke, heat, flood probabilities + status).

## Lane structure

- **Top-level** (`infer_parcel_state.py`, `parcel_first_hazard.py`, `serve_inference_api.py`): cross-version orchestrator. Dispatches per-lane behavior via `runtime_lane` parameter (see `oesis/common/runtime_lane.py`).
- **Per-version overlay dirs** (`v0_1/` through `v0_5/`): lane-specific implementations and overrides.

## v1.0 and v1.5 status

| Lane | Module dir | Status |
|---|---|---|
| v0.1 – v0.5 | `v0_1/` – `v0_5/` | Implemented |
| v1.0 | (no dedicated dir) | Lane-aware via top-level dispatch + `runtime_lane="v1.0"`; v1.0 inference deltas materialize through assets and config in `oesis/assets/v1.0/` |
| **v1.5** | **(no dir)** | **Contracts present in `oesis/assets/v1.5/examples/` (6 files) but no inference module exercises them yet.** v1.5 examples are validated against contract schemas via `oesis-contracts/scripts/validate_examples.py`, but the bridge-stage inference path (house-state, intervention-event, verification-outcome → parcel-state) is not yet implemented in this module. |

This is intentional — v1.5 is a draft additive lane, and runtime modules will land per their own ticketed work, not as a single lift. See [oesis-program-specs U7 #116](https://github.com/lumenaut-llc/oesis-program-specs/issues/116) for the bridge-endpoint tracker that gates this module's v1.5 work.

If you're exploring the tree and wondering whether v1.5 inference modules were lost: they were never written. The assets directory mirrors the contract; the module directory mirrors what's been implemented against the contract.
