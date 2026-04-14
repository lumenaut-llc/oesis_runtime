# v0.5 lane assets

Additive overrides for the `v0.5` runtime lane (governance enforcement).

Files placed here override the `v0.1` baseline during asset materialization
(`materialize_contracts_bundle`, `materialize_inference_config`). Any file not
overridden falls back to `v0.1`.

## Scope

v0.5 extends v0.4 with:

- **Consent lifecycle** — grant, revoke, status, history, private-summary enforcement
- **Retention cleanup** — prune old access log entries and completed rights requests past cutoff
- **Export bundle** — produce a portable parcel data export (sharing, rights, access events)
- **Revocation suppression** — revoked consent suppresses shared-map contributions
- Active sharing configuration (`neighborhood_aggregate: true`)
