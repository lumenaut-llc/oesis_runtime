# oesis.shared_map

Shared neighborhood-signal aggregation. Produces opt-in cross-parcel summaries with consent gating, custody-tier enforcement, and minimum-participation thresholding.

## Lane structure

- **Top-level** (`aggregate_shared_map.py`, `serve_shared_map_api.py`): cross-version orchestrator
- **Per-version overlay dirs** (`v0_1/` through `v1_0/`): lane-specific implementations and overrides

## v1.5 status

There is **no `v1_5/` dir in this module.** v1.5 is the bridge-stage capability lane (house-state, intervention-event, verification-outcome). Bridge-stage objects are private-by-default; they don't have shared-map projections defined yet. Whether the shared-map surface should expose any bridge-stage signal at all is itself an open design question (see UA2 contribution-schema design thread).

If `v1_5/` later appears here, it would carry whatever cross-parcel projection is approved for bridge-stage signals — likely a small, heavily-gated subset rather than direct mirroring of the bridge objects.

Cross-references:

- v1.5 bridge-object tracker: [oesis-program-specs U7 #116](https://github.com/lumenaut-llc/oesis-program-specs/issues/116)
- Contribution-schema design thread: [oesis-program-specs UA2 #62](https://github.com/lumenaut-llc/oesis-program-specs/issues/62)
