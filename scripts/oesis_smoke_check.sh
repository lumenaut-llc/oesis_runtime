#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[oesis-check] validating example payloads"
python3 -m oesis.ingest.validate_examples >/tmp/oesis-validate.out

echo "[oesis-check] running reference pipeline"
python3 -m oesis.parcel_platform.reference_pipeline >/tmp/oesis-demo.out

echo "[oesis-check] checking pipeline output shape (v0.1)"
python3 - <<'PY'
import json
from pathlib import Path

from oesis.checks.v01 import verify_runtime_flow_artifacts

payload = json.loads(Path("/tmp/oesis-demo.out").read_text(encoding="utf-8"))
verify_runtime_flow_artifacts(payload)

statuses = payload["parcel_view"]["statuses"]
for key in ("shelter", "reentry", "egress", "asset_risk"):
    if key not in statuses:
        raise SystemExit(f"parcel_view.statuses missing {key}")

print("PASS oesis-check")
PY
