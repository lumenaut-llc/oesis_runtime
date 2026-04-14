# v0.2 lane assets

Additive overrides for the `v0.2` runtime lane (indoor + sheltered-outdoor parcel kit).

Files placed here override the `v0.1` baseline during asset materialization
(`materialize_contracts_bundle`, `materialize_inference_config`). Any file not
overridden falls back to `v0.1`.

## Scope

v0.2 extends v0.1 with:

- **mast-lite** sheltered outdoor reference node alongside bench-air (indoor)
- Stronger node registry with installation metadata and calibration state
- Indoor vs sheltered-outdoor evidence source mix in parcel outputs
- Registry-driven node lifecycle
