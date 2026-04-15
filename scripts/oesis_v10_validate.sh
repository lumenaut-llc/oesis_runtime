#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONTRACTS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oesis-v10-contracts.XXXXXX")"
CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oesis-v10-config.XXXXXX")"

cleanup() {
  rm -rf "$CONTRACTS_DIR" "$CONFIG_DIR"
}
trap cleanup EXIT

python3 -m oesis.common.runtime_lane contracts-bundle --lane v1.0 --destination "$CONTRACTS_DIR" >/dev/null
python3 -m oesis.common.runtime_lane inference-config --lane v1.0 --destination "$CONFIG_DIR" >/dev/null

export OESIS_CONTRACTS_BUNDLE_DIR="$CONTRACTS_DIR"
export OESIS_INFERENCE_CONFIG_DIR="$CONFIG_DIR"
export OESIS_RUNTIME_LANE="v1.0"

echo "[oesis-v10-validate] validating v1.0 example payloads"
python3 -m oesis.ingest.validate_examples
