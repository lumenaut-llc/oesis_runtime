# OESIS Runtime

OESIS (Open Environmental Sensing and Inference System) is a runtime that turns raw sensor data into actionable environmental assessments for residential parcels. It ingests node packets (air quality, weather, flood level), runs inference against configurable hazard thresholds, and produces a parcel view — a dwelling-facing status surface summarizing conditions and risks.

Formal specifications and contracts live in [`oesis-program-specs`](https://github.com/lumenaut-llc/oesis-program-specs).

## Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Run the reference pipeline end-to-end (sensor packet in, parcel view out):

```bash
make oesis-demo
```

Run the full offline acceptance suite:

```bash
make oesis-check
```

## How it works

```
sensor packet ──► ingest ──► normalized observation
                                      │
                  parcel context ──────┤
                  public context ──────┤
                                       ▼
                                   inference ──► parcel state
                                                     │
                                                     ▼
                                              parcel view (dwelling-facing)
```

1. **Ingest** — validates and normalizes a raw node packet (e.g. `oesis.bench-air.v1`) into a standard observation.
2. **Inference** — combines the observation with parcel context (installed nodes, location) and public context (regional thresholds) to assess hazard levels.
3. **Parcel platform** — formats the inference result into a parcel view for the dwelling occupant.

## Commands

| Command | What it does |
|---------|--------------|
| `make oesis-demo` | Run the reference pipeline; prints the parcel view JSON to stdout. |
| `make oesis-validate` | Validate packaged example JSON against schemas. |
| `make oesis-check` | Validate examples, run demo, and verify output shape. |
| `make oesis-accept` | Offline acceptance: build the full flow and verify artifact shapes. |
| `make oesis-http-check` | Start local HTTP services and verify the full round-trip. |

## HTTP services

The runtime exposes three HTTP services for live operation:

```bash
# Start the ingest API (receives node packets)
python3 -m oesis.ingest.serve_ingest_api --host 127.0.0.1 --port 8787
```

**Endpoints:**

| Endpoint | Description |
|----------|-------------|
| `POST /v1/ingest/node-packets` | Submit a raw node packet for normalization. |
| `GET /v1/ingest/live` | Browser dashboard showing the last accepted observation. |
| `GET /v1/ingest/debug/last` | JSON of the last accepted observation (for scripts). |

For hardware on the LAN, bind with `--host 0.0.0.0` and use your machine's LAN IP.

### Serial bridge (hardware)

If you have a bench-air node emitting JSON over serial:

```bash
pip install -e ".[serial-bridge]"
python3 -m oesis.ingest.serial_bridge \
  --serial-port /dev/cu.usbmodem101 \
  --parcel-id parcel_demo_001
```

Use `--dry-run` to verify parsing without posting, or `--once` for a single packet.

## Runtime lanes

The runtime supports multiple capability lanes. Each lane builds on the previous one, adding new node types, inference features, or governance capabilities. The default lane is `v0.1`.

| Lane | What it adds | Commands |
|------|-------------|----------|
| **v0.1** (default) | One parcel, one bench-air node, one pipeline path. | `make oesis-check` |
| **v0.2** | Mast-lite node (sheltered outdoor) alongside bench-air. Indoor vs outdoor evidence source mix. | `make oesis-v02-check` |
| **v0.3** | Flood node (`oesis.flood-node.v1`). Three-node parcel kit: bench-air + mast-lite + flood. | `make oesis-v03-check` |
| **v0.4** | Node registry lifecycle (load, validate, filter). Multi-node evidence composition with calibration weighting. | `make oesis-v04-check` |
| **v0.5** | Governance enforcement: consent lifecycle, retention cleanup, data export, revocation suppression. | `make oesis-v05-check` |
| **v1.0** | Future target. | `make oesis-v10-check` |

Each lane also has `make oesis-v0X-accept` (offline acceptance) and `make oesis-v0X-http-check` (HTTP round-trip).

To select a lane, set the environment variable or pass a header:

```bash
# Via environment variable
OESIS_RUNTIME_LANE=v0.3 make oesis-demo

# Via HTTP header on API requests
curl -H "X-OESIS-Lane: v0.3" ...
```

Lanes work by overlaying lane-specific assets on the `v0.1` baseline. Files live under `oesis/assets/<lane>/` — anything not overridden falls back to `v0.1`. See [`pre-1.0-version-progression.md`](https://github.com/lumenaut-llc/oesis-program-specs/blob/main/architecture/current/pre-1.0-version-progression.md) for formal slice definitions.

## Versioning

Three independent version identifiers appear in this project:

| Identifier | Example | What it tracks |
|------------|---------|----------------|
| **Package version** | `0.1.0` in `pyproject.toml` | Installable release. Increments on code changes. |
| **Runtime lane** | `v0.1`–`v0.5`, `v1.0` | Which capability set is active. |
| **API version** | `v1` in `/v1/...` paths | HTTP wire protocol. |

These are independent — a new package release doesn't create a lane, and a new lane doesn't change the API version.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OESIS_RUNTIME_LANE` | `v0.1` | Active runtime lane. |
| `OESIS_CONTRACTS_BUNDLE_DIR` | `oesis/assets/v0.1/examples` | Custom examples directory. |
| `OESIS_INFERENCE_CONFIG_DIR` | `oesis/assets/v0.1/config/inference` | Custom inference config directory. |
| `OESIS_HTTP_INGEST_PORT` | `8787` | Ingest service port. |
| `OESIS_HTTP_INFERENCE_PORT` | `8788` | Inference service port. |
| `OESIS_HTTP_PARCEL_PORT` | `8789` | Parcel platform service port. |

## License

Licensed under the **GNU Affero General Public License v3.0 or later**. See [`LICENSE`](LICENSE). Contribution expectations: [`CONTRIBUTING.md`](CONTRIBUTING.md).
