#!/usr/bin/env python3

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from oesis.common.runtime_lane import (
    SUPPORTED_LANES,
    requested_lane_from_headers,
    resolve_runtime_lane,
    versioning_payload,
)
from oesis.inference import lane_module as inference_lane_module

MODEL_INFO = {
    "model_id": "hazard-logic-v0",
    "mode": "rules-based",
    "status": "active",
}


class InferenceRequestHandler(BaseHTTPRequestHandler):
    server_version = "OESISInference/0.1"

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"request body: invalid JSON: {exc}") from exc

    def do_GET(self):
        try:
            runtime_lane = resolve_runtime_lane(requested_lane_from_headers(self.headers))
        except SystemExit as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_runtime_lane", "detail": str(exc)})
            return
        if self.path == "/v1/inference/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "inference-engine",
                    "model": MODEL_INFO,
                    "versioning": {
                        **versioning_payload(lane=runtime_lane),
                        "supported_lanes": sorted(SUPPORTED_LANES),
                    },
                },
            )
            return

        if self.path == "/v1/inference/models":
            self._send_json(HTTPStatus.OK, {"models": [MODEL_INFO], "versioning": versioning_payload(lane=runtime_lane)})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/v1/inference/parcel-state":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        computed_at = self.headers.get("X-OESIS-Computed-At")
        try:
            runtime_lane = resolve_runtime_lane(requested_lane_from_headers(self.headers))
        except SystemExit as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "invalid_runtime_lane",
                    "detail": str(exc),
                },
            )
            return

        lane_infer = inference_lane_module("infer_parcel_state", lane=runtime_lane)
        InferenceError = lane_infer.InferenceError
        combine_public_contexts = lane_infer.combine_public_contexts
        infer_parcel_state = lane_infer.infer_parcel_state
        try:
            payload = self._read_json()
            normalized_observation = payload.get("normalized_observation", payload)
            parcel_context = payload.get("parcel_context")
            house_state = payload.get("house_state")
            house_capability = payload.get("house_capability")
            equipment_state_observation = payload.get("equipment_state_observation")
            source_provenance_record = payload.get("source_provenance_record")
            intervention_event = payload.get("intervention_event")
            verification_outcome = payload.get("verification_outcome")
            shared_neighborhood_context = payload.get("shared_neighborhood_context")
            public_context_payload = payload.get("public_context")
            public_contexts = payload.get("public_contexts", [])
            if public_context_payload and public_contexts:
                    raise InferenceError("request body must provide either public_context or public_contexts, not both")
            combined_public_context = None
            if public_contexts:
                combined_public_context = combine_public_contexts(public_contexts)
            elif public_context_payload:
                combined_public_context = public_context_payload
            parcel_state = infer_parcel_state(
                normalized_observation,
                computed_at=computed_at,
                runtime_lane=runtime_lane,
                parcel_context=parcel_context,
                house_state=house_state,
                house_capability=house_capability,
                equipment_state_observation=equipment_state_observation,
                source_provenance_record=source_provenance_record,
                intervention_event=intervention_event,
                verification_outcome=verification_outcome,
                shared_neighborhood_context=shared_neighborhood_context,
                public_context=combined_public_context,
            )
        except (InferenceError, ValueError, KeyError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "invalid_observation",
                    "detail": str(exc),
                },
            )
            return

        self._send_json(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "parcel_state": parcel_state,
                "versioning": versioning_payload(lane=runtime_lane),
            },
        )

    def log_message(self, format, *args):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny local inference API for normalized observation testing.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8788, help="Port to listen on.")
    return parser.parse_args()


def main():
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), InferenceRequestHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
