#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

: "${OESIS_HTTP_INGEST_PORT:=8787}"
: "${OESIS_HTTP_INFERENCE_PORT:=8788}"
: "${OESIS_HTTP_PARCEL_PORT:=8789}"
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
}
trap cleanup EXIT

echo "[oesis-http-check] starting ingest api (port ${OESIS_HTTP_INGEST_PORT})"
python3 -m oesis.ingest.serve_ingest_api --host 127.0.0.1 --port "${OESIS_HTTP_INGEST_PORT}" >/tmp/oesis-ingest.log 2>&1 &
INGEST_PID=$!

echo "[oesis-http-check] starting inference api (port ${OESIS_HTTP_INFERENCE_PORT})"
python3 -m oesis.inference.serve_inference_api --host 127.0.0.1 --port "${OESIS_HTTP_INFERENCE_PORT}" >/tmp/oesis-inference.log 2>&1 &
INFERENCE_PID=$!

echo "[oesis-http-check] starting parcel-platform api (port ${OESIS_HTTP_PARCEL_PORT})"
python3 -m oesis.parcel_platform.serve_parcel_api --host 127.0.0.1 --port "${OESIS_HTTP_PARCEL_PORT}" >/tmp/oesis-parcel.log 2>&1 &
PARCEL_PID=$!

echo "[oesis-http-check] waiting for health endpoints"
for i in $(seq 1 "${OESIS_HTTP_HEALTH_RETRIES}"); do
  if curl -sf "http://127.0.0.1:${OESIS_HTTP_INGEST_PORT}/v1/ingest/health" >/tmp/oesis-ingest-health.json \
    && curl -sf "http://127.0.0.1:${OESIS_HTTP_INFERENCE_PORT}/v1/inference/health" >/tmp/oesis-inference-health.json \
    && curl -sf "http://127.0.0.1:${OESIS_HTTP_PARCEL_PORT}/v1/parcel-platform/health" >/tmp/oesis-parcel-health.json; then
    break
  fi
  if [[ "$i" -eq "${OESIS_HTTP_HEALTH_RETRIES}" ]]; then
    echo "[oesis-http-check] ERROR: services did not become healthy in time (see /tmp/oesis-*.log)" >&2
    exit 1
  fi
  sleep "${OESIS_HTTP_HEALTH_INTERVAL_S}"
done

NODE_PACKET_EXAMPLE="$(python3 - <<'PY'
from oesis.common.repo_paths import EXAMPLES_DIR

print((EXAMPLES_DIR / "node-observation.example.json").resolve())
PY
)"

echo "[oesis-http-check] posting node packet to ingest api"
curl -s -X POST "http://127.0.0.1:${OESIS_HTTP_INGEST_PORT}/v1/ingest/node-packets" \
  -H 'Content-Type: application/json' \
  -H 'X-OESIS-Parcel-Id: parcel_demo_http' \
  --data-binary @"$NODE_PACKET_EXAMPLE" \
  >/tmp/oesis-ingest-response.json

echo "[oesis-http-check] building v0.1 inference request (normalized + parcel + public context)"
python3 - <<'PY'
import json
from pathlib import Path

from oesis.context import load_default_bundle
from oesis.ingest.v0_1.normalize_public_smoke_context import normalize_public_smoke_context
from oesis.ingest.v0_1.normalize_public_weather_context import normalize_public_weather_context
from oesis.inference import lane_module as inference_lane_module

combine_public_contexts = inference_lane_module("infer_parcel_state", lane="v0.1").combine_public_contexts

ingest = json.loads(Path("/tmp/oesis-ingest-response.json").read_text(encoding="utf-8"))
parcel_id = "parcel_demo_http"
bundle = load_default_bundle(parcel_id=parcel_id)
weather = normalize_public_weather_context(bundle["raw_public_weather"])
smoke = normalize_public_smoke_context(bundle["raw_public_smoke"])
public_context = combine_public_contexts([weather, smoke])
body = {
    "normalized_observation": ingest["normalized_observation"],
    "parcel_context": bundle["parcel_context"],
    "public_context": public_context,
}
Path("/tmp/oesis-inference-request.json").write_text(
    json.dumps(body),
    encoding="utf-8",
)
PY

curl -s -X POST "http://127.0.0.1:${OESIS_HTTP_INFERENCE_PORT}/v1/inference/parcel-state" \
  -H 'Content-Type: application/json' \
  -H 'X-OESIS-Computed-At: 2026-03-30T19:46:00Z' \
  --data-binary @/tmp/oesis-inference-request.json \
  >/tmp/oesis-inference-response.json

echo "[oesis-http-check] posting parcel state to parcel-platform api"
python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("/tmp/oesis-inference-response.json").read_text(encoding="utf-8"))
Path("/tmp/oesis-parcel-state-from-http.json").write_text(
    json.dumps(payload["parcel_state"]),
    encoding="utf-8",
)
PY

curl -s -X POST "http://127.0.0.1:${OESIS_HTTP_PARCEL_PORT}/v1/parcels/state/view" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/oesis-parcel-state-from-http.json \
  >/tmp/oesis-parcel-response.json

echo "[oesis-http-check] checking response shapes (v0.1)"
python3 - <<'PY'
import json
from pathlib import Path

from oesis.checks.v0_1.acceptance import verify_http_flow_artifacts


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))

ingest_health = load("/tmp/oesis-ingest-health.json")
inference_health = load("/tmp/oesis-inference-health.json")
parcel_health = load("/tmp/oesis-parcel-health.json")
ingest_payload = load("/tmp/oesis-ingest-response.json")
inference_payload = load("/tmp/oesis-inference-response.json")
parcel_payload = load("/tmp/oesis-parcel-response.json")

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

print("PASS oesis-http-check")
PY
