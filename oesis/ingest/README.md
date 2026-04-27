# oesis.ingest

Packet ingestion + normalization. Accepts raw packets from sensor nodes (bench-air, mast-lite, flood, weather-pm, circuit-monitor) and emits canonical normalized observations.

## Module shape

This module does NOT use per-version subdirectories. All normalizers live at the top level and dispatch by `schema_version` discriminator on the raw packet. Lane-aware behavior is parameterized via `runtime_lane`, not segregated into version dirs.

Files:

- `ingest_packet.py` — main entry point; routes by `schema_version`
- `normalize_packet.py` — bench-air baseline normalizer (covers v0.1–v0.5 lanes)
- `normalize_public_smoke_context.py`, `normalize_public_weather_context.py` — adapter normalizers for public context
- `serve_ingest_api.py` — HTTP boundary
- `serial_bridge.py` — node serial → ingest API bridge

## v1.0 and v1.5 status

| Surface | Status |
|---|---|
| `oesis.bench-air.v1` (v0.1+) | Implemented |
| `flood.low_point.snapshot` (v0.3+) | Implemented (separate `normalize_flood_packet.py` overlay per lane) |
| `air.pm_weather.snapshot` (v1.0) | Implemented (separate `normalize_weather_pm_packet.py` overlay per lane) |
| `equipment.circuit.snapshot` (v1.0+) | Schema landed in oesis-contracts 2026-04-24; runtime normalizer **not yet wired** |
| **v1.5 bridge contracts** (equipment-state-observation, source-provenance-record, etc.) | **Contracts present in `oesis/assets/v1.5/examples/` but no normalizer in this module exercises them yet.** Validation happens via `oesis-contracts/scripts/validate_examples.py`. |

v1.5 ingest work is gated on the bridge-endpoint tracker [oesis-program-specs U7 #116](https://github.com/lumenaut-llc/oesis-program-specs/issues/116). If you're exploring the tree and wondering whether v1.5 normalizers were lost: they were never written.
