# Data Model Examples

These JSON example payloads are intended as implementation scaffolding for the first MVP contracts.

- `node-observation.example.json`
  Example of a raw node packet from `oesis.bench-air.v1`.
- `node-registry.example.json`
  Example of a parcel-scoped registry binding multiple hardware nodes into one system.
- `normalized-observation.example.json`
  Example of the canonical observation object emitted by the ingest boundary.
- `parcel-state.example.json`
  Example of a homeowner-facing parcel-state snapshot after inference.
- `parcel-context.example.json`
  Example of parcel installation context and parcel priors supplied to inference.
- `public-context.example.json`
  Example of optional public external context supplied to inference as supporting evidence.
- `raw-public-weather.example.json`
  Example of a source-shaped public weather payload before adapter normalization.
- `raw-public-smoke.example.json`
  Example of a source-shaped public smoke payload before adapter normalization.
- `shared-neighborhood-signal.example.json`
  Example of a delayed, thresholded neighborhood signal object derived from opt-in shared contributions.

These examples should evolve with the prose contracts and the matching JSON Schema files in `../schemas/`.
