# v0.4 lane assets

Additive overrides for the `v0.4` runtime lane (multi-node registry + evidence composition).

Files placed here override the `v0.1` baseline during asset materialization
(`materialize_contracts_bundle`, `materialize_inference_config`). Any file not
overridden falls back to `v0.1`.

## Scope

v0.4 extends v0.3 with:

- **Node registry lifecycle** — load, validate, filter active nodes, bind registry metadata to observations
- **Multi-node evidence composition** — compose evidence across bench-air, mast-lite, and flood-node observations with calibration-weighted contributions
- **Source diversity tracking** — indoor/outdoor/sheltered coverage in composed evidence
- All three observation families from v0.3 (air snapshot, air snapshot via mast-lite, flood snapshot)
