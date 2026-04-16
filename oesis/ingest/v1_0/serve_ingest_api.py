#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from oesis.common.runtime_lane import (
    SUPPORTED_LANES,
    requested_lane_from_headers,
    resolve_runtime_lane,
    versioning_payload,
)

from .auth import authorize_ingest_request
from .normalize_packet import normalize_packet
from .validate_examples import ValidationError


SUPPORTED_SCHEMAS = ["oesis.bench-air.v1", "oesis.circuit-monitor.v1", "oesis.flood-node.v1", "oesis.weather-pm-mast.v1"]

_last_lock = threading.Lock()
_last_snapshot: dict | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_last_ingest(*, parcel_id: str, normalized: dict) -> None:
    global _last_snapshot
    with _last_lock:
        _last_snapshot = {
            "received_at": _now_iso(),
            "parcel_id": parcel_id,
            "normalized_observation": normalized,
        }


def _get_last_snapshot() -> dict | None:
    with _last_lock:
        if _last_snapshot is None:
            return None
        return dict(_last_snapshot)


def _request_path(raw_path: str) -> str:
    return raw_path.split("?", 1)[0]


LIVE_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>OESIS ingest — live</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1.25rem; max-width: 56rem; }
    h1 { font-size: 1.15rem; }
    .meta { color: #444; font-size: 0.9rem; margin: 0.5rem 0 1rem; }
    .err { color: #a30; }
    pre {
      background: #f4f4f5;
      padding: 1rem;
      overflow: auto;
      font-size: 0.8rem;
      border-radius: 6px;
    }
  </style>
</head>
<body>
  <h1>OESIS reference ingest — last accepted packet</h1>
  <p class="meta">Polling <code>/v1/ingest/debug/last</code> every second. In-memory only; restarts clear history.</p>
  <p id="status" class="meta">Loading…</p>
  <pre id="out">{}</pre>
  <script>
    const statusEl = document.getElementById("status");
    const outEl = document.getElementById("out");
    async function tick() {
      try {
        statusEl.classList.remove("err");
        const r = await fetch("/v1/ingest/debug/last", { cache: "no-store" });
        const j = await r.json();
        if (!j.ok) {
          statusEl.textContent = "Unexpected response";
          outEl.textContent = JSON.stringify(j, null, 2);
          return;
        }
        if (j.empty) {
          statusEl.textContent = "No packet ingested yet — POST to /v1/ingest/node-packets";
          outEl.textContent = JSON.stringify(j, null, 2);
          return;
        }
        statusEl.textContent =
          "Last ingest at " + j.received_at + " (UTC). Parcel: " + (j.parcel_id || "?");
        outEl.textContent = JSON.stringify(j, null, 2);
      } catch (e) {
        statusEl.textContent = "Fetch failed";
        outEl.textContent = String(e);
        statusEl.classList.add("err");
      }
    }
    tick();
    setInterval(tick, 1000);
  </script>
</body>
</html>
"""


class IngestRequestHandler(BaseHTTPRequestHandler):
    server_version = "OESISIngest/0.1"
    api_key: str | None = None
    node_registry: dict | None = None

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
        path = _request_path(self.path)
        try:
            runtime_lane = resolve_runtime_lane(requested_lane_from_headers(self.headers))
        except SystemExit as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_runtime_lane", "detail": str(exc)})
            return
        if path == "/v1/ingest/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "ingest-service",
                    "supported_schemas": SUPPORTED_SCHEMAS,
                    "versioning": {
                        **versioning_payload(lane=runtime_lane),
                        "supported_lanes": sorted(SUPPORTED_LANES),
                    },
                },
            )
            return

        if path == "/v1/ingest/schemas":
            self._send_json(
                HTTPStatus.OK,
                {
                    "schemas": [
                        {
                            "schema_version": "oesis.bench-air.v1",
                            "status": "active",
                        },
                        {
                            "schema_version": "oesis.circuit-monitor.v1",
                            "status": "active",
                        },
                        {
                            "schema_version": "oesis.flood-node.v1",
                            "status": "active",
                        },
                        {
                            "schema_version": "oesis.weather-pm-mast.v1",
                            "status": "active",
                        },
                    ],
                    "versioning": versioning_payload(lane=runtime_lane),
                },
            )
            return

        if path == "/v1/ingest/debug/last":
            snap = _get_last_snapshot()
            if snap is None:
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "empty": True,
                        "message": "no packets ingested yet",
                        "versioning": versioning_payload(lane=runtime_lane),
                    },
                )
            else:
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "empty": False,
                        **snap,
                        "versioning": versioning_payload(lane=runtime_lane),
                    },
                )
            return

        if path == "/v1/ingest/live":
            self._send_html(HTTPStatus.OK, LIVE_PAGE_HTML)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        path = _request_path(self.path)
        if path != "/v1/ingest/node-packets":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        # Authorization check (opt-in via env vars)
        auth_result = authorize_ingest_request(
            self.headers,
            api_key=self.__class__.api_key,
            registry=self.__class__.node_registry,
        )
        if not auth_result.authorized:
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {
                    "ok": False,
                    "error": "unauthorized",
                    "detail": auth_result.rejection_reason,
                },
            )
            return

        parcel_id = self.headers.get("X-OESIS-Parcel-Id", "parcel_demo_001")
        try:
            runtime_lane = resolve_runtime_lane(requested_lane_from_headers(self.headers))
            payload = self._read_json()
            normalized = normalize_packet(payload, parcel_id=parcel_id, runtime_lane=runtime_lane)
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

        _record_last_ingest(parcel_id=parcel_id, normalized=normalized)
        self._send_json(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "normalized_observation": normalized,
                "versioning": versioning_payload(lane=runtime_lane),
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

    # Opt-in authorization from environment
    api_key = os.environ.get("OESIS_INGEST_API_KEY")
    registry_path = os.environ.get("OESIS_NODE_REGISTRY_PATH")
    if api_key:
        IngestRequestHandler.api_key = api_key
        print("Authorization: API key required (OESIS_INGEST_API_KEY set)")
    if registry_path:
        try:
            IngestRequestHandler.node_registry = json.loads(
                Path(registry_path).read_text(encoding="utf-8")
            )
            node_count = len(IngestRequestHandler.node_registry.get("nodes", []))
            print(f"Authorization: node registry loaded ({node_count} nodes from {registry_path})")
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARNING: could not load node registry from {registry_path}: {exc}")

    server = ThreadingHTTPServer((args.host, args.port), IngestRequestHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    print(f"Live dashboard: http://{args.host}:{args.port}/v1/ingest/live")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
