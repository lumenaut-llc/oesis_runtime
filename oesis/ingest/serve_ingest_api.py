#!/usr/bin/env python3

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .normalize_packet import normalize_packet
from .validate_examples import ValidationError


SUPPORTED_SCHEMAS = ["oesis.bench-air.v1"]


class IngestRequestHandler(BaseHTTPRequestHandler):
    server_version = "OESISIngest/0.1"

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
            raise ValidationError(f"request body: invalid JSON: {exc}") from exc

    def do_GET(self):
        if self.path == "/v1/ingest/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "ingest-service",
                    "supported_schemas": SUPPORTED_SCHEMAS,
                },
            )
            return

        if self.path == "/v1/ingest/schemas":
            self._send_json(
                HTTPStatus.OK,
                {
                    "schemas": [
                        {
                            "schema_version": "oesis.bench-air.v1",
                            "status": "active",
                        }
                    ]
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/v1/ingest/node-packets":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        parcel_id = self.headers.get("X-OESIS-Parcel-Id", "parcel_demo_001")
        try:
            payload = self._read_json()
            normalized = normalize_packet(payload, parcel_id=parcel_id)
        except (ValidationError, KeyError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "invalid_packet",
                    "detail": str(exc),
                },
            )
            return

        self._send_json(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "normalized_observation": normalized,
            },
        )

    def log_message(self, format, *args):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny local ingest API for bench-air packet testing.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8787, help="Port to listen on.")
    return parser.parse_args()


def main():
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), IngestRequestHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
