# Assets v0.1

This directory is the canonical baseline lane for runtime-shipped assets.

## Scope

- `examples/`: baseline JSON example payloads used by local checks and demos.
- `config/inference/`: baseline inference configuration assets.

Bridge and later-stage support objects may temporarily appear in this lane for
compatibility, but they are non-baseline and should not gate `v0.1` acceptance.

## Compatibility

Legacy unversioned paths are deprecated. Runtime loaders use this `v0.1` lane as
the baseline source of truth.
