#!/usr/bin/env python3

import argparse
import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR, REPO_ROOT

from .format_evidence_summary import build_evidence_summary
from .format_parcel_view import ParcelViewError, build_parcel_view, validate_sharing_settings
from .run_retention_cleanup import run_cleanup
from .summarize_reference_state import load_optional_json as load_optional_reference_json
from .summarize_reference_state import summarize as summarize_reference_state

EXAMPLES_DIR = DOCS_EXAMPLES_DIR
DEFAULT_SHARING = json.loads((EXAMPLES_DIR / "sharing-settings.example.json").read_text(encoding="utf-8"))
DEFAULT_RIGHTS_REQUEST = json.loads((EXAMPLES_DIR / "rights-request.example.json").read_text(encoding="utf-8"))
DEFAULT_SHARING_STORE = json.loads((EXAMPLES_DIR / "sharing-store.example.json").read_text(encoding="utf-8"))
DEFAULT_RIGHTS_REQUEST_STORE = json.loads((EXAMPLES_DIR / "rights-request-store.example.json").read_text(encoding="utf-8"))
DEFAULT_EXPORT_BUNDLE = json.loads((EXAMPLES_DIR / "export-bundle.example.json").read_text(encoding="utf-8"))

_STORE_LOCKS: dict[Path, threading.RLock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _store_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _STORE_LOCKS_GUARD:
        lock = _STORE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _STORE_LOCKS[resolved] = lock
        return lock


def _read_json_unlocked(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _load_json_store_unlocked(path: Path, default_payload):
    if path.exists():
        return _read_json_unlocked(path)
    payload = deepcopy(default_payload)
    _atomic_write_json(path, payload)
    return payload


def _save_json_store_unlocked(path: Path, payload, *, touch_updated_at: bool):
    stored = deepcopy(payload)
    if touch_updated_at:
        stored["updated_at"] = now_iso()
    _atomic_write_json(path, stored)
    return stored


def _load_access_log_unlocked(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return _read_json_unlocked(path)


def load_access_log(path: Path) -> list[dict]:
    resolved = path.resolve()
    with _store_lock(resolved):
        return deepcopy(_load_access_log_unlocked(resolved))


def _save_access_log_unlocked(path: Path, payload: list[dict]):
    _atomic_write_json(path, payload)


def ensure_path_within_allowed_roots(path: Path, *, allowed_roots: list[Path], label: str) -> Path:
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    allowed = ", ".join(str(root.resolve()) for root in allowed_roots)
    raise ParcelViewError(f"{label} must stay within one of: {allowed}")


def resolve_export_output_path(export_dir: Path, output_name: str) -> Path:
    export_root = export_dir.resolve()
    return ensure_path_within_allowed_roots(
        export_root / output_name,
        allowed_roots=[export_root],
        label="output_name",
    )


def resolve_allowed_input_path(raw_path: str, *, allowed_roots: list[Path], label: str) -> Path:
    return ensure_path_within_allowed_roots(
        Path(raw_path),
        allowed_roots=allowed_roots,
        label=label,
    )


def clone_default_sharing(parcel_id: str) -> dict:
    payload = deepcopy(DEFAULT_SHARING)
    payload["parcel_id"] = parcel_id
    payload["updated_at"] = now_iso()
    return payload


def parcel_ref_for_id(parcel_id: str) -> str:
    return f"parcel_ref_{parcel_id}"


def build_rights_request(parcel_id: str, request_type: str) -> dict:
    payload = deepcopy(DEFAULT_RIGHTS_REQUEST)
    payload["request_id"] = f"rights_{request_type}_{parcel_id}"
    payload["parcel_id"] = parcel_id
    payload["request_type"] = request_type
    payload["created_at"] = now_iso()
    payload["status"] = "submitted"
    return payload


def load_sharing_store(path: Path) -> dict:
    resolved = path.resolve()
    with _store_lock(resolved):
        return deepcopy(_load_json_store_unlocked(resolved, DEFAULT_SHARING_STORE))


def save_sharing_store(path: Path, payload: dict):
    resolved = path.resolve()
    with _store_lock(resolved):
        _save_json_store_unlocked(resolved, payload, touch_updated_at=True)


def load_rights_store(path: Path) -> dict:
    resolved = path.resolve()
    with _store_lock(resolved):
        return deepcopy(_load_json_store_unlocked(resolved, DEFAULT_RIGHTS_REQUEST_STORE))


def save_rights_store(path: Path, payload: dict):
    resolved = path.resolve()
    with _store_lock(resolved):
        _save_json_store_unlocked(resolved, payload, touch_updated_at=True)


def append_rights_request(path: Path, request: dict):
    resolved = path.resolve()
    with _store_lock(resolved):
        store = _load_json_store_unlocked(resolved, DEFAULT_RIGHTS_REQUEST_STORE)
        store["requests"].append(deepcopy(request))
        _save_json_store_unlocked(resolved, store, touch_updated_at=True)


def list_rights_requests(path: Path, parcel_id: str) -> list[dict]:
    resolved = path.resolve()
    with _store_lock(resolved):
        store = _load_json_store_unlocked(resolved, DEFAULT_RIGHTS_REQUEST_STORE)
        return [deepcopy(item) for item in store["requests"] if item["parcel_id"] == parcel_id]


def update_rights_request_status(path: Path, request_id: str, status: str) -> dict:
    resolved = path.resolve()
    with _store_lock(resolved):
        store = _load_json_store_unlocked(resolved, DEFAULT_RIGHTS_REQUEST_STORE)
        for request in store["requests"]:
            if request["request_id"] == request_id:
                request["status"] = status
                _save_json_store_unlocked(resolved, store, touch_updated_at=True)
                return deepcopy(request)
        raise KeyError(f"rights request not found: {request_id}")


def remove_parcel_from_sharing_store(path: Path, parcel_id: str):
    resolved = path.resolve()
    with _store_lock(resolved):
        store = _load_json_store_unlocked(resolved, DEFAULT_SHARING_STORE)
        store["parcels"] = [entry for entry in store["parcels"] if entry["parcel_id"] != parcel_id]
        _save_json_store_unlocked(resolved, store, touch_updated_at=True)


def process_delete_request(rights_store_path: Path, sharing_store_path: Path, request_id: str) -> dict:
    rights_path = rights_store_path.resolve()
    with _store_lock(rights_path):
        store = _load_json_store_unlocked(rights_path, DEFAULT_RIGHTS_REQUEST_STORE)
        for request in store["requests"]:
            if request["request_id"] != request_id:
                continue
            if request["request_type"] != "delete":
                raise KeyError(f"rights request is not a delete request: {request_id}")
            request["status"] = "completed"
            _save_json_store_unlocked(rights_path, store, touch_updated_at=True)
            remove_parcel_from_sharing_store(sharing_store_path, request["parcel_id"])
            return deepcopy(request)
    raise KeyError(f"rights request not found: {request_id}")


def export_bundle_for_parcel(parcel_id: str, sharing_store_path: Path, rights_store_path: Path, access_log_path: Path, parcel_state_path: Path | None = None) -> dict:
    sharing = None
    sharing_store = load_sharing_store(sharing_store_path)
    for entry in sharing_store["parcels"]:
        if entry["parcel_id"] == parcel_id:
            sharing = deepcopy(entry["sharing"])
            break

    rights_requests = list_rights_requests(rights_store_path, parcel_id)
    access_events = [deepcopy(event) for event in load_access_log(access_log_path) if event["parcel_id"] == parcel_id]

    parcel_state = None
    if parcel_state_path and parcel_state_path.exists():
        payload = json.loads(parcel_state_path.read_text(encoding="utf-8"))
        if payload.get("parcel_id") == parcel_id:
            parcel_state = payload
    if parcel_state is None:
        payload = deepcopy(DEFAULT_EXPORT_BUNDLE["parcel_state"])
        if payload.get("parcel_id") == parcel_id:
            parcel_state = payload

    return {
        "generated_at": now_iso(),
        "parcel_id": parcel_id,
        "sharing": sharing,
        "rights_requests": rights_requests,
        "access_events": access_events,
        "parcel_state": parcel_state,
    }


def process_export_request(rights_store_path: Path, sharing_store_path: Path, access_log_path: Path, request_id: str, output_path: Path, parcel_state_path: Path | None = None) -> dict:
    rights_path = rights_store_path.resolve()
    with _store_lock(rights_path):
        store = _load_json_store_unlocked(rights_path, DEFAULT_RIGHTS_REQUEST_STORE)
        for request in store["requests"]:
            if request["request_id"] != request_id:
                continue
            if request["request_type"] != "export":
                raise KeyError(f"rights request is not an export request: {request_id}")
            request["status"] = "completed"
            _save_json_store_unlocked(rights_path, store, touch_updated_at=True)
            bundle = export_bundle_for_parcel(
                request["parcel_id"],
                sharing_store_path,
                rights_store_path,
                access_log_path,
                parcel_state_path=parcel_state_path,
            )
            output_path = output_path.resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(output_path, bundle)
            return deepcopy(request)
    raise KeyError(f"rights request not found: {request_id}")


def build_reference_state_summary(sharing_store_path: Path, rights_store_path: Path, access_log_path: Path) -> dict:
    sharing_store = load_optional_reference_json(sharing_store_path, {"updated_at": None, "parcels": []})
    rights_store = load_optional_reference_json(rights_store_path, {"updated_at": None, "requests": []})
    access_log = load_optional_reference_json(access_log_path, [])
    return summarize_reference_state(sharing_store, rights_store, access_log)


def append_access_event(path: Path, *, actor: str, action: str, parcel_id: str, data_classes: list[str], justification: str):
    resolved = path.resolve()
    with _store_lock(resolved):
        payload = _load_access_log_unlocked(resolved)
        payload.append(
            {
                "event_id": f"access_{action}_{parcel_id}_{len(payload)+1}",
                "occurred_at": now_iso(),
                "actor": actor,
                "action": action,
                "parcel_id": parcel_id,
                "data_classes": data_classes,
                "justification": justification,
            }
        )
        _save_access_log_unlocked(resolved, payload)


def sharing_from_store(path: Path, parcel_id: str) -> dict:
    resolved = path.resolve()
    with _store_lock(resolved):
        store = _load_json_store_unlocked(resolved, DEFAULT_SHARING_STORE)
        for entry in store["parcels"]:
            if entry["parcel_id"] == parcel_id:
                return deepcopy(entry["sharing"])
        sharing = clone_default_sharing(parcel_id)
        store["parcels"].append(
            {
                "parcel_id": parcel_id,
                "parcel_ref": parcel_ref_for_id(parcel_id),
                "sharing": deepcopy(sharing),
            }
        )
        _save_json_store_unlocked(resolved, store, touch_updated_at=True)
        return sharing


def update_sharing_store(path: Path, parcel_id: str, sharing: dict):
    resolved = path.resolve()
    with _store_lock(resolved):
        store = _load_json_store_unlocked(resolved, DEFAULT_SHARING_STORE)
        for entry in store["parcels"]:
            if entry["parcel_id"] == parcel_id:
                entry["sharing"] = deepcopy(sharing)
                entry["parcel_ref"] = entry.get("parcel_ref") or parcel_ref_for_id(parcel_id)
                _save_json_store_unlocked(resolved, store, touch_updated_at=True)
                return
        store["parcels"].append(
            {
                "parcel_id": parcel_id,
                "parcel_ref": parcel_ref_for_id(parcel_id),
                "sharing": deepcopy(sharing),
            }
        )
        _save_json_store_unlocked(resolved, store, touch_updated_at=True)


class ParcelPlatformRequestHandler(BaseHTTPRequestHandler):
    server_version = "OESISParcelPlatform/0.1"
    sharing_store_path = None
    rights_store_path = None
    access_log_path = None
    export_dir_path = None
    allowed_input_roots = []

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
            raise ParcelViewError(f"request body: invalid JSON: {exc}") from exc

    def _path_parts(self):
        return [part for part in self.path.split("/") if part]

    def _sharing_for_parcel(self, parcel_id: str) -> dict:
        return sharing_from_store(self.sharing_store_path, parcel_id)

    def do_GET(self):
        if self.path == "/v1/parcel-platform/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "parcel-platform",
                },
            )
            return

        if self.path == "/v1/admin/reference-state/summary":
            try:
                summary = build_reference_state_summary(
                    self.sharing_store_path,
                    self.rights_store_path,
                    self.access_log_path,
                )
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "reference_state_unavailable",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "summary": summary,
                },
            )
            return

        parts = self._path_parts()
        if len(parts) == 4 and parts[:2] == ["v1", "parcels"] and parts[3] == "sharing":
            parcel_id = parts[2]
            append_access_event(
                self.access_log_path,
                actor="parcel-platform-api",
                action="view_sharing_settings",
                parcel_id=parcel_id,
                data_classes=["administrative_record"],
                justification="sharing_settings_request",
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "sharing": self._sharing_for_parcel(parcel_id),
                },
            )
            return

        if len(parts) == 4 and parts[:2] == ["v1", "parcels"] and parts[3] == "rights":
            parcel_id = parts[2]
            append_access_event(
                self.access_log_path,
                actor="parcel-platform-api",
                action="list_rights_requests",
                parcel_id=parcel_id,
                data_classes=["administrative_record"],
                justification="rights_request_status_view",
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "rights_requests": list_rights_requests(self.rights_store_path, parcel_id),
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/v1/parcels/state/view":
            try:
                payload = self._read_json()
                parcel_id = payload["parcel_id"]
                sharing_settings = self._sharing_for_parcel(parcel_id)
                parcel_view = build_parcel_view(payload, sharing_settings)
                append_access_event(
                    self.access_log_path,
                    actor="parcel-platform-api",
                    action="view_parcel_state",
                    parcel_id=parcel_id,
                    data_classes=["private_parcel_data", "derived_parcel_state"],
                    justification="parcel_view_request",
                )
            except (ParcelViewError, KeyError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_parcel_state",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "parcel_view": parcel_view,
                },
            )
            return

        if self.path == "/v1/parcels/state/evidence-summary":
            try:
                payload = self._read_json()
                parcel_id = payload["parcel_id"]
                evidence_summary = build_evidence_summary(payload)
                append_access_event(
                    self.access_log_path,
                    actor="parcel-platform-api",
                    action="view_evidence_summary",
                    parcel_id=parcel_id,
                    data_classes=["derived_parcel_state"],
                    justification="evidence_summary_request",
                )
            except (ParcelViewError, KeyError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_parcel_state",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "evidence_summary": evidence_summary,
                },
            )
            return

        parts = self._path_parts()
        if len(parts) == 4 and parts[:2] == ["v1", "parcels"] and parts[3] == "sharing":
            parcel_id = parts[2]
            try:
                payload = self._read_json()
                payload["parcel_id"] = parcel_id
                payload["updated_at"] = now_iso()
                validate_sharing_settings(payload)
                update_sharing_store(self.sharing_store_path, parcel_id, payload)
                append_access_event(
                    self.access_log_path,
                    actor="parcel-platform-api",
                    action="update_sharing_settings",
                    parcel_id=parcel_id,
                    data_classes=["administrative_record"],
                    justification="sharing_settings_update",
                )
            except (ParcelViewError, KeyError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_sharing_settings",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "sharing": self._sharing_for_parcel(parcel_id),
                },
            )
            return

        if len(parts) == 5 and parts[:2] == ["v1", "parcels"] and parts[3] == "rights" and parts[4] in {"export", "delete"}:
            parcel_id = parts[2]
            request_type = parts[4]
            rights_request = build_rights_request(parcel_id, request_type)
            append_rights_request(self.rights_store_path, rights_request)
            append_access_event(
                self.access_log_path,
                actor="parcel-platform-api",
                action=f"create_{request_type}_request",
                parcel_id=parcel_id,
                data_classes=["administrative_record"],
                justification="rights_request_submission",
            )
            self._send_json(
                HTTPStatus.ACCEPTED,
                {
                    "ok": True,
                    "rights_request": rights_request,
                },
            )
            return

        if self.path == "/v1/admin/rights/process-delete":
            try:
                payload = self._read_json()
                request_id = payload["request_id"]
                result = process_delete_request(
                    self.rights_store_path,
                    self.sharing_store_path,
                    request_id,
                )
                append_access_event(
                    self.access_log_path,
                    actor="parcel-platform-api",
                    action="process_delete_request",
                    parcel_id=result["parcel_id"],
                    data_classes=["administrative_record"],
                    justification="delete_request_execution",
                )
            except (ParcelViewError, KeyError, OSError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_delete_request",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "rights_request": result,
                },
            )
            return

        if self.path == "/v1/admin/rights/process-export":
            try:
                payload = self._read_json()
                request_id = payload["request_id"]
                output_name = payload.get("output_name", f"{request_id}.json")
                output_path = resolve_export_output_path(self.export_dir_path, output_name)
                parcel_state_path = None
                if payload.get("parcel_state_path"):
                    allowed_roots = [*self.allowed_input_roots, self.export_dir_path]
                    parcel_state_path = resolve_allowed_input_path(
                        payload["parcel_state_path"],
                        allowed_roots=allowed_roots,
                        label="parcel_state_path",
                    )
                result = process_export_request(
                    self.rights_store_path,
                    self.sharing_store_path,
                    self.access_log_path,
                    request_id,
                    output_path,
                    parcel_state_path=parcel_state_path,
                )
                append_access_event(
                    self.access_log_path,
                    actor="parcel-platform-api",
                    action="process_export_request",
                    parcel_id=result["parcel_id"],
                    data_classes=["administrative_record"],
                    justification="export_request_execution",
                )
            except (ParcelViewError, KeyError, OSError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_export_request",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "rights_request": result,
                    "output_path": str(output_path),
                },
            )
            return

        if self.path == "/v1/admin/retention/cleanup":
            try:
                payload = self._read_json()
                retention_days = int(payload.get("retention_days", 30))
                report = run_cleanup(
                    rights_store_path=self.rights_store_path,
                    access_log_path=self.access_log_path,
                    retention_days=retention_days,
                )
            except (ParcelViewError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_retention_cleanup_request",
                        "detail": str(exc),
                    },
                )
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "cleanup_report": report,
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format, *args):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny local parcel-platform API for parcel-state formatting.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8789, help="Port to listen on.")
    parser.add_argument(
        "--sharing-store",
        default="/tmp/oesis-sharing-store.json",
        help="Path to a JSON sharing store file used across reference services.",
    )
    parser.add_argument(
        "--rights-store",
        default="/tmp/oesis-rights-request-store.json",
        help="Path to a JSON rights-request store file.",
    )
    parser.add_argument(
        "--access-log",
        default="/tmp/oesis-operator-access-log.json",
        help="Path to a JSON operator access log file.",
    )
    parser.add_argument(
        "--export-dir",
        default="/tmp/oesis-parcel-exports",
        help="Directory for reference export bundles written by admin export processing endpoints.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    ParcelPlatformRequestHandler.sharing_store_path = Path(args.sharing_store).resolve()
    ParcelPlatformRequestHandler.rights_store_path = Path(args.rights_store).resolve()
    ParcelPlatformRequestHandler.access_log_path = Path(args.access_log).resolve()
    ParcelPlatformRequestHandler.export_dir_path = Path(args.export_dir).resolve()
    ParcelPlatformRequestHandler.allowed_input_roots = [REPO_ROOT.resolve()]
    ParcelPlatformRequestHandler.export_dir_path.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), ParcelPlatformRequestHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
