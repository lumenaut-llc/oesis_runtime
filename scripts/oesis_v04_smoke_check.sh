#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONTRACTS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oesis-v04-contracts.XXXXXX")"
CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oesis-v04-config.XXXXXX")"

cleanup() {
  rm -rf "$CONTRACTS_DIR" "$CONFIG_DIR"
}
trap cleanup EXIT

python3 -m oesis.common.runtime_lane contracts-bundle --lane v0.4 --destination "$CONTRACTS_DIR" >/dev/null
python3 -m oesis.common.runtime_lane inference-config --lane v0.4 --destination "$CONFIG_DIR" >/dev/null

export OESIS_CONTRACTS_BUNDLE_DIR="$CONTRACTS_DIR"
export OESIS_INFERENCE_CONFIG_DIR="$CONFIG_DIR"
export OESIS_RUNTIME_LANE="v0.4"

echo "[oesis-v04-check] validating example payloads"
python3 -m oesis.ingest.validate_examples >/tmp/oesis-v04-validate.out

echo "[oesis-v04-check] running reference pipeline"
python3 -m oesis.parcel_platform.reference_pipeline >/tmp/oesis-v04-demo.out

echo "[oesis-v04-check] checking pipeline output shape (v0.4 lane)"
python3 - <<'PY'
import json
from pathlib import Path

from oesis.checks.v0_4.acceptance import verify_runtime_flow_artifacts

payload = json.loads(Path("/tmp/oesis-v04-demo.out").read_text(encoding="utf-8"))
verify_runtime_flow_artifacts(payload)

statuses = payload["parcel_view"]["statuses"]
for key in ("shelter", "reentry", "egress", "asset_risk"):
    if key not in statuses:
        raise SystemExit(f"parcel_view.statuses missing {key}")

print("PASS oesis-v04-check")
PY
