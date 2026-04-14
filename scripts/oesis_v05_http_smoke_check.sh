#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONTRACTS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oesis-v05-contracts.XXXXXX")"
CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oesis-v05-config.XXXXXX")"

python3 -m oesis.common.runtime_lane contracts-bundle --lane v0.5 --destination "$CONTRACTS_DIR" >/dev/null
python3 -m oesis.common.runtime_lane inference-config --lane v0.5 --destination "$CONFIG_DIR" >/dev/null

export OESIS_CONTRACTS_BUNDLE_DIR="$CONTRACTS_DIR"
export OESIS_INFERENCE_CONFIG_DIR="$CONFIG_DIR"
export OESIS_RUNTIME_LANE="v0.5"

: "${OESIS_HTTP_INGEST_PORT:=8797}"
: "${OESIS_HTTP_INFERENCE_PORT:=8798}"
: "${OESIS_HTTP_PARCEL_PORT:=8799}"
: "${OESIS_HTTP_HEALTH_RETRIES:=30}"
: "${OESIS_HTTP_HEALTH_INTERVAL_S:=0.2}"

INGEST_PID=""
INFERENCE_PID=""
PARCEL_PID=""

cleanup() {
  for pid in "$PARCEL_PID" "$INFERENCE_PID" "$INGEST_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -rf "$CONTRACTS_DIR" "$CONFIG_DIR"
}
trap cleanup EXIT

echo "[oesis-v05-http-check] starting ingest api (port ${OESIS_HTTP_INGEST_PORT})"
python3 -m oesis.ingest.serve_ingest_api --host 127.0.0.1 --port "${OESIS_HTTP_INGEST_PORT}" >/tmp/oesis-v05-ingest.log 2>&1 &
INGEST_PID=$!

echo "[oesis-v05-http-check] starting inference api (port ${OESIS_HTTP_INFERENCE_PORT})"
python3 -m oesis.inference.serve_inference_api --host 127.0.0.1 --port "${OESIS_HTTP_INFERENCE_PORT}" >/tmp/oesis-v05-inference.log 2>&1 &
INFERENCE_PID=$!

echo "[oesis-v05-http-check] starting parcel-platform api (port ${OESIS_HTTP_PARCEL_PORT})"
python3 -m oesis.parcel_platform.serve_parcel_api --host 127.0.0.1 --port "${OESIS_HTTP_PARCEL_PORT}" >/tmp/oesis-v05-parcel.log 2>&1 &
PARCEL_PID=$!

echo "[oesis-v05-http-check] waiting for health endpoints"
for i in $(seq 1 "${OESIS_HTTP_HEALTH_RETRIES}"); do
  if curl -sf "http://127.0.0.1:${OESIS_HTTP_INGEST_PORT}/v1/ingest/health" >/tmp/oesis-v05-ingest-health.json \
    && curl -sf "http://127.0.0.1:${OESIS_HTTP_INFERENCE_PORT}/v1/inference/health" >/tmp/oesis-v05-inference-health.json \
    && curl -sf "http://127.0.0.1:${OESIS_HTTP_PARCEL_PORT}/v1/parcel-platform/health" >/tmp/oesis-v05-parcel-health.json; then
    break
  fi
  if [[ "$i" -eq "${OESIS_HTTP_HEALTH_RETRIES}" ]]; then
    echo "[oesis-v05-http-check] ERROR: services did not become healthy in time (see /tmp/oesis-v05-*.log)" >&2
    exit 1
  fi
  sleep "${OESIS_HTTP_HEALTH_INTERVAL_S}"
done

NODE_PACKET_EXAMPLE="$(python3 - <<'PY'
from pathlib import Path
import os

bundle_root = Path(os.environ["OESIS_CONTRACTS_BUNDLE_DIR"]).resolve()
print((bundle_root / "examples" / "node-observation.example.json").resolve())
PY
)"

echo "[oesis-v05-http-check] posting node packet to ingest api"
curl -s -X POST "http://127.0.0.1:${OESIS_HTTP_INGEST_PORT}/v1/ingest/node-packets" \
  -H 'Content-Type: application/json' \
  -H 'X-OESIS-Parcel-Id: parcel_demo_http_v05' \
  --data-binary @"$NODE_PACKET_EXAMPLE" \
  >/tmp/oesis-v05-ingest-response.json

echo "[oesis-v05-http-check] building v0.5 inference request (normalized + parcel + public context)"
python3 - <<'PY'
import json
from pathlib import Path

from oesis.context import load_default_bundle
from oesis.ingest.v0_5.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v0_5.normalize_public_weather_context import normalize_public_weather_context
from oesis.inference import lane_module as inference_lane_module

combine_public_contexts = inference_lane_module("infer_parcel_state", lane="v0.5").combine_public_contexts

ingest = json.loads(Path("/tmp/oesis-v05-ingest-response.json").read_text(encoding="utf-8"))
parcel_id = "parcel_demo_http_v05"
bundle = load_default_bundle(parcel_id=parcel_id)
weather = normalize_public_weather_context(bundle["raw_public_weather"])
smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
public_context = combine_public_contexts([weather, smoke])
body = {
    "normalized_observation": ingest["normalized_observation"],
    "parcel_context": bundle["parcel_context"],
    "public_context": public_context,
}
Path("/tmp/oesis-v05-inference-request.json").write_text(
    json.dumps(body),
    encoding="utf-8",
)
PY

curl -s -X POST "http://127.0.0.1:${OESIS_HTTP_INFERENCE_PORT}/v1/inference/parcel-state" \
  -H 'Content-Type: application/json' \
  -H 'X-OESIS-Computed-At: 2026-03-30T19:46:00Z' \
  --data-binary @/tmp/oesis-v05-inference-request.json \
  >/tmp/oesis-v05-inference-response.json

echo "[oesis-v05-http-check] posting parcel state to parcel-platform api"
python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("/tmp/oesis-v05-inference-response.json").read_text(encoding="utf-8"))
Path("/tmp/oesis-v05-parcel-state-from-http.json").write_text(
    json.dumps(payload["parcel_state"]),
    encoding="utf-8",
)
PY

curl -s -X POST "http://127.0.0.1:${OESIS_HTTP_PARCEL_PORT}/v1/parcels/state/view" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/oesis-v05-parcel-state-from-http.json \
  >/tmp/oesis-v05-parcel-response.json

echo "[oesis-v05-http-check] checking response shapes (v0.5 lane)"
python3 - <<'PY'
import json
from pathlib import Path

from oesis.checks.v0_5.acceptance import verify_http_flow_artifacts

def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))

ingest_health = load("/tmp/oesis-v05-ingest-health.json")
inference_health = load("/tmp/oesis-v05-inference-health.json")
parcel_health = load("/tmp/oesis-v05-parcel-health.json")
ingest_payload = load("/tmp/oesis-v05-ingest-response.json")
inference_payload = load("/tmp/oesis-v05-inference-response.json")
parcel_payload = load("/tmp/oesis-v05-parcel-response.json")

verify_http_flow_artifacts(
    ingest_health=ingest_health,
    inference_health=inference_health,
    parcel_health=parcel_health,
    ingest_payload=ingest_payload,
    inference_payload=inference_payload,
    parcel_payload=parcel_payload,
)

statuses = parcel_payload["parcel_view"]["statuses"]
for key in ("shelter", "reentry", "egress", "asset_risk"):
    if key not in statuses:
        raise SystemExit(f"parcel_view.statuses missing {key}")

print("PASS oesis-v05-http-check")
PY
