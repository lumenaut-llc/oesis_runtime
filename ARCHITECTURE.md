# ARCHITECTURE

## Purpose

Describe how `oesis-runtime` is structured internally, how the lane overlay
system works, and how modules connect to form the end-to-end processing
pipeline. This document is for contributors who need to understand the codebase
before making changes.

For the cross-repo system view (how this repo fits into the broader OESIS
architecture), see
[cross-repo-architecture.md](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/cross-repo-architecture.md)
in oesis-program-specs.

## Module structure

```
oesis/
├── ingest/                 Packet ingestion and normalization
│   ├── v0_1/               Baseline normalizers (bench-air)
│   ├── v0_2/               Two-node kit (bench-air + mast-lite)
│   ├── v0_3/               Flood-capable (3-node)
│   ├── v0_4/               Multi-node registry
│   ├── v0_5/               Governance enforcement
│   ├── v1_0/               Extended node families (weather-PM, circuit-monitor)
│   └── v1_5/               Bridge support objects
├── inference/              Hazard assessment engine
│   ├── v0_1/               Single-hazard inference
│   ├── v0_2/ – v1_0/      Progressive capability additions
│   └── v1_5/               Bridge inference
├── parcel_platform/        Output formatting and APIs
│   ├── v0_1/               Basic parcel view
│   ├── v0_4/               Evidence composition
│   ├── v0_5/               Governance (consent, retention, export, rights)
│   └── v1_0/               Trust scoring, support objects
├── context/                Lane-specific example and config loaders
├── common/                 Shared utilities and lane resolution
│   └── runtime_lane.py     Lane discovery, asset materialization
├── checks/                 Offline acceptance test harness
│   ├── __main__.py          Entry point: python3 -m oesis.checks --lane <lane>
│   ├── v0_1/ – v1_0/       Per-lane acceptance builders and verifiers
│   └── acceptance.py        Shared verification utilities
├── shared_map/             Neighborhood-level aggregate APIs
└── assets/                 Configuration and example files (see below)
```

## Lane overlay system

Lanes are the central versioning concept in the runtime. Each lane represents a
capability set that the system can activate.

### Canonical lanes (must match specs)

| Lane | Scope |
|------|-------|
| v0.1 | Baseline: one parcel, one bench-air node, single-hazard inference |
| v1.0 | Extended: weather-PM, circuit-monitor, trust scoring, support objects |
| v1.5 | Bridge: equipment state, indoor response, power outage |

Canonical lane examples are byte-identical between this repo and
oesis-program-specs. CI enforces this via `cross-repo-example-sync`.

### Overlay lanes (runtime test fixtures)

| Lane | Scope |
|------|-------|
| v0.2 | Two-node kit (bench-air + mast-lite) |
| v0.3 | Flood-capable (3-node) |
| v0.4 | Multi-node registry + evidence composition |
| v0.5 | Governance enforcement (consent, retention, export, revocation) |

Overlay lanes have test fixtures that specs does not track. They exist to test
progressive capability additions.

### Asset materialization

All lanes build on v0.1 as the base. When a non-default lane is activated:

1. `resolve_runtime_lane()` determines the active lane from argument, env var
   (`OESIS_RUNTIME_LANE`), or default
2. `materialize_contracts_bundle(dest, lane)` copies v0.1 examples, then
   overlays lane-specific examples on top
3. `materialize_inference_config(dest, lane)` copies v0.1 configs, then
   overlays lane-specific configs on top

```
oesis/assets/
├── v0.1/
│   ├── examples/           33 baseline JSON examples
│   └── config/inference/   5 baseline config files
├── v0.2/ through v1.5/
│   ├── examples/           Lane-specific overrides
│   └── config/inference/   Lane-specific config overrides
└── examples/               Root-level examples (shared across lanes)
```

## Data flow pipeline

```
 Raw sensor packet          Normalized observation       Parcel state           Parcel view
 (from hardware node)       (schema-validated)           (hazard assessment)    (dwelling-facing)
        │                          │                          │                       │
        ▼                          ▼                          ▼                       ▼
 ┌─────────────┐          ┌────────────────┐         ┌──────────────┐        ┌──────────────┐
 │   INGEST    │─────────▶│   INFERENCE    │────────▶│   PARCEL     │───────▶│  SHARED MAP  │
 │             │          │                │         │   PLATFORM   │        │  (optional)  │
 └─────────────┘          └────────────────┘         └──────────────┘        └──────────────┘

 normalize_packet()        infer_parcel_state()        format_parcel_view()    aggregate + serve
 normalize_flood_packet()  parcel_first_hazard()       format_evidence()
 normalize_weather_pm()                                export_parcel_bundle()
                                                       process_rights_requests()
```

### Ingest phase (`oesis.ingest`)

Validates raw sensor packets against serial-JSON contracts, normalizes them into
the `normalized-observation` schema. Each node family has its own normalizer:

- `normalize_packet.py` — bench-air (PM2.5, temperature, humidity)
- `normalize_flood_packet.py` — flood (water level, rate of change)
- `normalize_weather_pm_packet.py` — weather-PM (outdoor PM, wind, pressure)
- `normalize_public_weather_context.py` — regional weather context
- `normalize_public_smoke_context.py` — regional smoke context

**Admissibility (planned — program-phase `v0.2` / Milestone 2, capability-stage `current v1`):** ingest will also produce
`admissible_to_calibration_dataset: bool` plus `admissibility_reasons: [string]`
on each normalized observation per
[`calibration-program.md`](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/calibration-program.md)
§C (physical sensors) or
[`adapter-trust-program.md`](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/adapter-trust-program.md)
§C (adapter-derived data). The decision is runtime-computed; the facts it
depends on are carried in the canonical observation schema — tracked as gap
G17 in oesis-program-specs. Branch is selected by the observation's
`adapter_tier` field (absent or `tier_3_direct` → calibration-program rules;
`tier_1_passive` or `tier_2_adapter` → adapter-trust-program rules).

### Inference phase (`oesis.inference`)

Combines normalized observations with public context and parcel priors to
produce a `parcel-state`. Key logic:

- PM2.5 correction using Barkjohn formula with relative humidity bands
- Hazard thresholds from `hazard_thresholds_v0.json`
- Public context weighting from `public_context_policy.json`
- Divergence analysis from `divergence_rules_v0.json`
- Trust gates from `trust_gates_v0.json`
- Contrastive explanations showing what evidence drove each status

### Platform phase (`oesis.parcel_platform`)

Formats parcel state into dwelling-facing views, manages governance (v0.5+),
and serves HTTP APIs:

- `format_parcel_view.py` — status, confidence, freshness, summary
- `format_evidence_summary.py` — detailed evidence breakdown
- `serve_parcel_api.py` — HTTP API for parcel views and governance
- `export_parcel_bundle.py` — data export for rights requests
- `run_retention_cleanup.py` — data retention enforcement

### Shared map (`oesis.shared_map`)

Aggregates parcel-level signals to neighborhood level for the public site.
Applies suppression rules (minimum parcels, differential privacy).

## HTTP services

| Service | Entry point | Default port | Endpoints |
|---------|------------|-------------|-----------|
| Ingest API | `python3 -m oesis.ingest.serve_ingest_api` | 8001 | `/v1/ingest/node-packets`, `/v1/ingest/live` |
| Parcel API | `python3 -m oesis.parcel_platform.serve_parcel_api` | 8002 | Parcel views, governance, rights requests |
| Shared Map API | `python3 -m oesis.shared_map.serve_shared_map_api` | 8003 | Neighborhood aggregates |

## Acceptance testing

The acceptance harness validates the full pipeline for each lane:

```bash
# Run all checks for a specific lane
python3 -m oesis.checks --lane v0.1

# Run via Makefile
make oesis-check          # v0.1 baseline
make oesis-v10-check      # v1.0 lane
```

Each lane's acceptance builder:
1. Loads the lane's example bundle
2. Runs the full pipeline (ingest → inference → platform)
3. Calls `verify_runtime_flow_artifacts()` to validate output shapes
4. Checks field presence, value ranges, and schema compliance

## Configuration files

All under `oesis/assets/<lane>/config/inference/`:

| File | Purpose |
|------|---------|
| `hazard_thresholds_v0.json` | PM2.5, flooding thresholds per hazard type |
| `public_context_policy.json` | Weights for combining weather + smoke evidence |
| `parcel_prior_rules_v0.json` | Base probabilities for parcel characteristics |
| `divergence_rules_v0.json` | PM2.5 correction factors (Barkjohn, RH bands) |
| `trust_gates_v0.json` | Confidence cutoffs for status determination |

## Key design decisions

1. **Specs defines, runtime implements.** Contract shapes always originate in
   oesis-program-specs. Runtime never creates schemas that specs does not own.

2. **Additive lanes.** Each lane overlays on v0.1 rather than forking. This
   means v0.1 assets are always present and higher lanes only add or override.

3. **Offline-first acceptance.** All acceptance tests run without network access,
   using example files from the assets directory.

4. **Lane-versioned modules.** Each processing phase has per-lane Python
   packages (`v0_1`, `v0_2`, etc.) rather than feature flags. This keeps each
   lane's logic isolated and testable.

5. **Dynamic lane import.** `lane_module(module_name, lane)` resolves to the
   correct versioned package at runtime, enabling lane switching without code
   changes.

## Related documents

- [cross-repo-architecture.md](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/cross-repo-architecture.md) — how all 4 repos work together
- [version-and-promotion-matrix.md](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/version-and-promotion-matrix.md) — four-axis versioning model
- [calibration-program.md](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/calibration-program.md) — physical-sensor calibration policy; §C admissibility rule; §F build-spec metadata block
- [adapter-trust-program.md](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/system/adapter-trust-program.md) — adapter trust policy for Tier 1 / Tier 2 data (capability-stage v1.5)
- [README.md](README.md) — getting started, quick demo, lane commands
