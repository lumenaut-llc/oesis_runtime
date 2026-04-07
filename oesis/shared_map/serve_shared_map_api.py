#!/usr/bin/env python3

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .aggregate_shared_map import SharedMapError, aggregate_shared_map, eligibility_from_store, load_sharing_store


LEGEND = {
    "shared_signal_status": {
        "visible": "Shared neighborhood signal shown because participation threshold is met.",
        "suppressed": "Shared neighborhood signal hidden because participation threshold is not met.",
    },
    "coverage_notice": "Neighborhood conditions are delayed and aggregated. Participation is partial.",
}


def build_shared_map_inspection(payload: dict, *, sharing_store: dict | None = None) -> dict:
    shared_map = aggregate_shared_map(payload, sharing_store=sharing_store)
    eligible_refs = []
    if sharing_store is not None:
        eligible_refs = sorted(
            parcel_ref
            for parcel_ref, enabled in eligibility_from_store(sharing_store).items()
            if enabled
        )
    visible_cells = [cell for cell in shared_map["cells"] if cell["shared_signal_status"] == "visible"]
    suppressed_cells = [cell for cell in shared_map["cells"] if cell["shared_signal_status"] == "suppressed"]
    return {
        "shared_map": shared_map,
        "inspection": {
            "cell_count": len(shared_map["cells"]),
            "visible_cell_count": len(visible_cells),
            "suppressed_cell_count": len(suppressed_cells),
            "min_participants": shared_map["min_participants"],
            "eligible_shared_ref_count": len(eligible_refs) if sharing_store is not None else None,
            "eligible_shared_refs": eligible_refs if sharing_store is not None else None,
            "public_map_supported": False,
            "coverage_notice": LEGEND["coverage_notice"],
        },
    }


class SharedMapRequestHandler(BaseHTTPRequestHandler):
    server_version = "OESISSharedMap/0.1"
    sharing_store_path = None

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
            raise SharedMapError(f"request body: invalid JSON: {exc}") from exc

    def _configured_sharing_store(self):
        if self.sharing_store_path is None:
            return None
        return load_sharing_store(self.sharing_store_path)

    def do_GET(self):
        if self.path == "/v1/shared-map/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "shared-map"})
            return
        if self.path == "/v1/shared-map/legend":
            self._send_json(HTTPStatus.OK, {"legend": LEGEND})
            return
        if self.path == "/v1/shared-map/coverage":
            self._send_json(
                HTTPStatus.OK,
                {
                    "coverage_notice": LEGEND["coverage_notice"],
                    "public_map_supported": False,
                    "sharing_store_configured": self.sharing_store_path is not None,
                },
            )
            return
        if self.path == "/v1/admin/shared-map/config":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "config": {
                        "public_map_supported": False,
                        "coverage_notice": LEGEND["coverage_notice"],
                        "sharing_store_configured": self.sharing_store_path is not None,
                        "sharing_store_path": str(self.sharing_store_path) if self.sharing_store_path else None,
                    },
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self.path in {"/v1/shared-map/tiles", "/v1/admin/shared-map/inspect"}:
            try:
                payload = self._read_json()
                sharing_store = self._configured_sharing_store()
                if self.path == "/v1/shared-map/tiles":
                    result = aggregate_shared_map(payload, sharing_store=sharing_store)
                else:
                    result = build_shared_map_inspection(payload, sharing_store=sharing_store)
            except (SharedMapError, KeyError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_shared_map_input",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(HTTPStatus.OK, {"ok": True, **result})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format, *args):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny local shared-map API for aggregated neighborhood testing.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8792, help="Port to listen on.")
    parser.add_argument(
        "--sharing-store",
        default=None,
        help="Optional path to a JSON sharing store file used to determine neighborhood eligibility.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    SharedMapRequestHandler.sharing_store_path = Path(args.sharing_store).resolve() if args.sharing_store else None
    server = ThreadingHTTPServer((args.host, args.port), SharedMapRequestHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
