# OESIS Runtime

Standalone runtime for the Open Environmental Sensing and Inference System reference path: ingest, inference, parcel platform, and smoke fixtures. The program specifications and contracts live in the sibling repository `../oesis-program-specs` (or your checkout of that tree).

## Program operating packet

**`oesis-program-specs`** remains canonical for contracts, schemas, and formal architecture. The **operating packet** (framing, phasing, KPIs, risks) lives under [`program/operating-packet/`](../oesis-program-specs/program/operating-packet/README.md) in the sibling checkout:

- **[`00-version-labels-and-lanes.md`](../oesis-program-specs/program/operating-packet/00-version-labels-and-lanes.md)** — read first: program phases vs runtime `v0.1` / optional `v1.0` lane vs public release language.
- **[`01-core-thesis-and-framing.md`](../oesis-program-specs/program/operating-packet/01-core-thesis-and-framing.md)** — thesis and positioning; then **`02`**–**`11`** in order in that folder:
  - [`02-problem-opportunity-and-market-gap.md`](../oesis-program-specs/program/operating-packet/02-problem-opportunity-and-market-gap.md)
  - [`03-originality-and-positioning.md`](../oesis-program-specs/program/operating-packet/03-originality-and-positioning.md)
  - [`04-architecture-review-keep-dangerous-change-now.md`](../oesis-program-specs/program/operating-packet/04-architecture-review-keep-dangerous-change-now.md)
  - [`05-revised-architecture-blueprint.md`](../oesis-program-specs/program/operating-packet/05-revised-architecture-blueprint.md)
  - [`06-network-of-networks-concepts.md`](../oesis-program-specs/program/operating-packet/06-network-of-networks-concepts.md)
  - [`07-information-layer-and-functional-recovery.md`](../oesis-program-specs/program/operating-packet/07-information-layer-and-functional-recovery.md)
  - [`08-kpi-framework.md`](../oesis-program-specs/program/operating-packet/08-kpi-framework.md)
  - [`09-phasing-v0.1-v1.0-v1.5.md`](../oesis-program-specs/program/operating-packet/09-phasing-v0.1-v1.0-v1.5.md)
  - [`10-outside-concepts-and-technology-pull-forward.md`](../oesis-program-specs/program/operating-packet/10-outside-concepts-and-technology-pull-forward.md)
  - [`11-next-docs-to-write.md`](../oesis-program-specs/program/operating-packet/11-next-docs-to-write.md)
- **[`functional-state-and-response-model.md`](../oesis-program-specs/program/operating-packet/functional-state-and-response-model.md)** — hazard vs functional vs response state and how they land by phase (with [`05`](../oesis-program-specs/program/operating-packet/05-revised-architecture-blueprint.md) and [`09`](../oesis-program-specs/program/operating-packet/09-phasing-v0.1-v1.0-v1.5.md)).

## Setup

From this repository root (recommended: use a virtual environment):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

After that, `python3 -m oesis...` and the `Makefile` targets work from any current working directory.

Keep packaged examples under `oesis/assets/v0.1/examples/` in sync with `contracts/examples/` in **oesis-program-specs** when you change contracts.

## v0.1 product slice (frozen scope, evolving implementation)

The v0.1 scope is frozen — no new capabilities are added. The implementation and examples continue to evolve within that scope (bug fixes, multi-hazard generalization, clearer examples). Implementation and acceptance tests target:

- **One parcel** — a single `parcel_id` and parcel-context fixture for demos and checks.
- **One bench-air node** — `oesis.bench-air.v1` packets; default fixture uses `bench-air-01`.
- **One software path** — ingest → normalized observation, plus parcel and public context → inference → parcel view (and evidence summary on the offline path).
- **One parcel view** — dwelling-facing status surface from the parcel platform formatter.

Canonical write-ups in **oesis-program-specs**: `architecture/current/v0.1-runtime-modules.md` (package map) and `architecture/current/v0.1-acceptance-criteria.md` (CLI/HTTP acceptance).

## Quick commands

| Target | What it does |
|--------|----------------|
| `make oesis-validate` | Validate packaged example JSON against schemas. |
| `make oesis-demo` | Run the reference pipeline (packet → parcel view); prints JSON on stdout. |
| `make oesis-accept` | Offline v0.1 acceptance: build flow + verify artifact shapes (`python3 -m oesis.checks`). |
| `make oesis-check` | Validate examples, run demo, verify output shape (CLI path). |
| `make oesis-http-check` | Start local HTTP services and verify ingest → inference → parcel view. |

These default commands remain pinned to the `v0.1` scope.

## Bench-air serial → ingest bridge

With hardware emitting one `oesis.bench-air.v1` JSON line per interval (see **oesis-program-specs** `hardware/bench-air-node/operator-runbook.md`), you can forward packets to the local ingest API without copying files:

```bash
pip install -e ".[serial-bridge]"
python3 -m oesis.ingest.serve_ingest_api --host 127.0.0.1 --port 8787   # separate terminal
python3 -m oesis.ingest.serial_bridge --serial-port /dev/cu.usbmodem101 --parcel-id parcel_demo_001
```

Use `--dry-run` to confirm lines parse on the wire, or `--once` for a single post. Defaults match `make oesis-http-check` (`127.0.0.1:8787`, path `/v1/ingest/node-packets`).

## Ingest live dashboard (operator)

While `serve_ingest_api` is running, open **`http://<host>:<port>/v1/ingest/live`** in a browser to poll the **last accepted** normalized observation (in-memory only; process restart clears it). JSON for scripts: **`GET /v1/ingest/debug/last`**. For hardware on the LAN, bind ingest with **`--host 0.0.0.0`** and use your machine’s LAN IP in the URL.

## Parallel lanes

This repository carries explicit opt-in lanes beside the frozen default.
See `oesis-program-specs/architecture/current/pre-1.0-version-progression.md` for the formal slice definitions.

### v0.2 lane (indoor + sheltered-outdoor parcel kit)

- `make oesis-v02-accept`
- `make oesis-v02-check`
- `make oesis-v02-http-check`

v0.2 extends v0.1 with mast-lite (sheltered outdoor node) alongside bench-air
(indoor), stronger node registry, and indoor vs outdoor evidence source mix.

### v0.3 lane (flood-capable runtime)

- `make oesis-v03-accept`
- `make oesis-v03-check`
- `make oesis-v03-http-check`

v0.3 extends v0.2 with a flood-node (`oesis.flood-node.v1` schema,
`flood.low_point.snapshot` observation type) giving a three-node parcel kit
(bench-air + mast-lite + flood-node).

### v0.4 lane (multi-node registry + evidence composition)

- `make oesis-v04-accept`
- `make oesis-v04-check`
- `make oesis-v04-http-check`

v0.4 extends v0.3 with node registry lifecycle (load, validate, filter active,
bind to observations) and multi-node evidence composition with
calibration-weighted contributions and source diversity tracking.

### v0.5 lane (governance enforcement)

- `make oesis-v05-accept`
- `make oesis-v05-check`
- `make oesis-v05-http-check`

v0.5 extends v0.4 with real governance enforcement: consent lifecycle (grant,
revoke, status, history), retention cleanup, export bundles, and revocation
suppression in the shared map.

### v1.0 lane (future target)

- `make oesis-v10-accept`
- `make oesis-v10-check`
- `make oesis-v10-http-check`

All lane commands materialize a merged asset set from:

- baseline `oesis/assets/v0.1/` (examples and inference config)
- additive overrides under `oesis/assets/<lane>/`

This keeps `v0.1` stable by default while giving each lane a real parallel home.
If a lane does not yet override a file, the `v0.1` baseline remains the
explicit fallback for that opt-in lane only.

## Pre-1.0 lane policy

The runtime models all v0.x slices as real lanes alongside the frozen `v0.1` default and the `v1.0` future target. Each slice builds on the previous one.

**Program-specs** defines promotions formally in sibling [`oesis-program-specs/architecture/current/pre-1.0-version-progression.md`](../oesis-program-specs/architecture/current/pre-1.0-version-progression.md) and the promotion matrix at [`oesis-program-specs/architecture/system/version-and-promotion-matrix.md`](../oesis-program-specs/architecture/system/version-and-promotion-matrix.md).

Current lanes:

- **`v0.1`** — frozen default runtime slice (one parcel, one bench-air node)
- **`v0.2`** — indoor + sheltered-outdoor parcel kit (bench-air + mast-lite)
- **`v0.3`** — flood-capable runtime (bench-air + mast-lite + flood-node)
- **`v0.4`** — multi-node registry lifecycle + evidence composition
- **`v0.5`** — governance enforcement (consent, retention, export, revocation)
- **`v1.0`** — additive future lane staging area

## Version axes

Three version identifiers appear in this project. They track different concerns:

| Identifier | Where | What it tracks |
|------------|-------|----------------|
| Package version (`0.1.0` in `pyproject.toml`) | Python packaging | Installable release of the runtime implementation. Increments on code changes. |
| Runtime lane (`v0.1`–`v0.5`, `v1.0`) | `OESIS_RUNTIME_LANE`, `X-OESIS-Lane` header | Which asset and behavior set is active. Lanes are defined in `oesis-program-specs`. |
| API version (`v1`) | HTTP path prefix `/v1/...`, `versioning.api_version` in payloads | HTTP service contract. Tracks the wire protocol, not the program phase or lane. |

These are independent. A package release `0.2.0` does not create a new lane; a new lane does not change the HTTP API version.

## Optional environment overrides

- `OESIS_CONTRACTS_BUNDLE_DIR` — directory containing an `examples/` subtree to use instead of `oesis/assets/v0.1/examples`.
- `OESIS_INFERENCE_CONFIG_DIR` — directory with `public_context_policy.json`, `hazard_thresholds_v0.json`, `trust_gates_v0.json` instead of `oesis/assets/v0.1/config/inference/`.
- `OESIS_RUNTIME_LANE` — explicit runtime lane (for example `v0.1`, `v0.3`, `v1.0`); defaults to `v0.1`.
- HTTP smoke (`make oesis-http-check`): `OESIS_HTTP_INGEST_PORT`, `OESIS_HTTP_INFERENCE_PORT`, `OESIS_HTTP_PARCEL_PORT` (defaults `8787`–`8789`); `OESIS_HTTP_HEALTH_RETRIES` (default `30`); `OESIS_HTTP_HEALTH_INTERVAL_S` (default `0.2`).

The lane helper scripts (`oesis_v02_*`, `oesis_v03_*`, ..., `oesis_v10_*`) use
those same override hooks explicitly. They do not change the root defaults for
`python3 -m oesis.checks`, `make oesis-accept`, or the root asset paths.

For per-request API override, services also accept `X-OESIS-Lane`.

## License

This reference runtime is licensed under the **GNU Affero General Public License v3.0 or later**. See [`LICENSE`](LICENSE). Contribution expectations: [`CONTRIBUTING.md`](CONTRIBUTING.md).
