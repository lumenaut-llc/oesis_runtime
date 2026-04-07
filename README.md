# OESIS Runtime

Standalone runtime for the Open Environmental Sensing and Inference System reference path: ingest, inference, parcel platform, and smoke fixtures. The program specifications and contracts live in the sibling repository `../oesis-program-specs` (or your checkout of that tree).

## v0.1 product slice (frozen scope)

Implementation and acceptance tests target:

- **One parcel** — a single `parcel_id` and parcel-context fixture for demos and checks.
- **One bench-air node** — `oesis.bench-air.v1` packets; default fixture uses `bench-air-01`.
- **One software path** — ingest → normalized observation, plus parcel and public context → inference → parcel view (and evidence summary on the offline path).
- **One parcel view** — homeowner-facing status surface from the parcel platform formatter.

## Quick commands

| Target | What it does |
|--------|----------------|
| `make oesis-validate` | Validate packaged example JSON against schemas. |
| `make oesis-demo` | Run the reference pipeline (packet → parcel view); prints JSON on stdout. |
| `make oesis-accept` | Offline v0.1 acceptance: build flow + verify artifact shapes (`python3 -m oesis.checks`). |
| `make oesis-check` | Validate examples, run demo, verify output shape (CLI path). |
| `make oesis-http-check` | Start local HTTP services and verify ingest → inference → parcel view. |

## Optional environment overrides

- `OESIS_CONTRACTS_BUNDLE_DIR` — directory containing an `examples/` subtree to use instead of `oesis/assets/examples`.
- `OESIS_INFERENCE_CONFIG_DIR` — directory with `public_context_policy.json`, `hazard_thresholds_v0.json`, `trust_gates_v0.json` instead of `oesis/assets/config/inference/`.
