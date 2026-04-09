# Example JSON payloads (runtime)

These files are **execution fixtures** shipped with `oesis-runtime` for demos,
validation, and smoke tests. They are aligned with the canonical contracts in
the **program-specs** repository.

This directory is the frozen default `v0.1` fixture surface.

**Canonical schemas and contract prose** live in the sibling checkout **`../oesis-program-specs`** under:

- `contracts/schemas/` — JSON Schema definitions
- `contracts/*.md` — schema documentation
- `contracts/examples/` — published examples (keep runtime copies in sync when contracts change)

Future-lane runtime overrides live in `../v1.0/examples/` and must only be used
through the explicit `oesis-v10-*` commands or equivalent environment
configuration.

Runtime files here include:

- `node-observation.example.json` — raw node packet from `oesis.bench-air.v1`.
- `node-registry.example.json` — parcel-scoped registry binding multiple hardware nodes.
- `normalized-observation.example.json` — canonical observation after ingest.
- `parcel-state.example.json` — parcel-state snapshot after inference.
- `parcel-context.example.json` — parcel installation context and priors for inference.
- `public-context.example.json` — optional public external context for inference.
- `raw-public-weather.example.json` — source-shaped weather payload before adapter normalization.
- `raw-public-smoke.example.json` — source-shaped smoke payload before adapter normalization.
- `shared-neighborhood-signal.example.json` — delayed, thresholded neighborhood signal from opt-in shared contributions.
