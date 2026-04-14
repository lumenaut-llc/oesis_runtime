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

## v0.1 product slice (frozen scope)

Implementation and acceptance tests target:

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

These default commands remain pinned to the frozen `v0.1` slice.

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

## Parallel v1.0 lane

This repository also carries an explicit opt-in `v1.0` lane beside the frozen
default:

- `make oesis-v10-accept`
- `make oesis-v10-check`
- `make oesis-v10-http-check`

Those commands materialize a merged future-lane asset set from:

- baseline `oesis/assets/v0.1/` (examples and inference config)
- additive overrides under `oesis/assets/v1.0/`

This keeps `v0.1` stable by default while giving `v1.0` a real parallel home.
If the `v1.0` lane does not yet override a file, the `v0.1` baseline remains
the explicit fallback for that opt-in lane only.

## Pre-1.0 lane policy

The runtime is intentionally not modeling separate asset overlays for `v0.2`, `v0.3`, and later slices yet.

**Program-specs** still defines those promotions formally (for example **`v0.2`** = accepted indoor + sheltered-outdoor kit with evidence) in sibling [`oesis-program-specs/architecture/current/pre-1.0-version-progression.md`](../oesis-program-specs/architecture/current/pre-1.0-version-progression.md) and the promotion matrix at [`oesis-program-specs/architecture/system/version-and-promotion-matrix.md`](../oesis-program-specs/architecture/system/version-and-promotion-matrix.md). Until this repo adds matching lanes, exercise widened behavior through milestones, optional `v1.0` overrides, and implementation-status tracking—not by inventing informal version names here.

For now:

- keep `v0.1` as the frozen default runtime slice
- use milestones and implementation-status docs for smaller compatible growth
- use the additive future lane as the staging area for the next broader slice
- only generalize runtime lane tooling after a second accepted pre-`1.0` slice
  is real enough to justify new asset overlays, commands, and acceptance paths

## Optional environment overrides

- `OESIS_CONTRACTS_BUNDLE_DIR` — directory containing an `examples/` subtree to use instead of `oesis/assets/v0.1/examples`.
- `OESIS_INFERENCE_CONFIG_DIR` — directory with `public_context_policy.json`, `hazard_thresholds_v0.json`, `trust_gates_v0.json` instead of `oesis/assets/v0.1/config/inference/`.
- `OESIS_RUNTIME_LANE` — explicit runtime lane (for example `v0.1`, `v1.0`); defaults to `v0.1`.
- HTTP smoke (`make oesis-http-check`): `OESIS_HTTP_INGEST_PORT`, `OESIS_HTTP_INFERENCE_PORT`, `OESIS_HTTP_PARCEL_PORT` (defaults `8787`–`8789`); `OESIS_HTTP_HEALTH_RETRIES` (default `30`); `OESIS_HTTP_HEALTH_INTERVAL_S` (default `0.2`).

The `v1.0` helper scripts use those same override hooks explicitly. They do not
change the root defaults for `python3 -m oesis.checks`, `make oesis-accept`, or
the root asset paths.

For per-request API override, services also accept `X-OESIS-Lane`.

## License

This reference runtime is licensed under the **GNU Affero General Public License v3.0 or later**. See [`LICENSE`](LICENSE). Contribution expectations: [`CONTRIBUTING.md`](CONTRIBUTING.md).
