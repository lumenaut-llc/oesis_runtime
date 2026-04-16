"""HTTP-level governance enforcement tests (GL-6 extension, V05-G14).

Proves that consent and revocation enforcement works at the HTTP API level,
not just the store level. Spins up a ParcelPlatformRequestHandler in-process
and makes real HTTP calls.
"""

from __future__ import annotations

import json
import tempfile
import threading
import urllib.request
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path

from oesis.common.runtime_lane import resolve_runtime_lane
from oesis.parcel_platform.v1_0.serve_parcel_api import (
    DEFAULT_CONSENT_STORE,
    DEFAULT_SHARING_STORE,
    DEFAULT_RIGHTS_REQUEST_STORE,
    ParcelPlatformRequestHandler,
)


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    """POST JSON and return (status_code, response_dict)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.request.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get_json(url: str) -> tuple[int, dict]:
    """GET JSON and return (status_code, response_dict)."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.request.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    resolve_runtime_lane()  # ensure lane is set

    with tempfile.TemporaryDirectory(prefix="oesis-v10-http-gov-") as temp_dir:
        temp = Path(temp_dir)

        # Initialize stores
        consent_path = temp / "consent-store.json"
        sharing_path = temp / "sharing-store.json"
        rights_path = temp / "rights-store.json"
        access_log_path = temp / "access-log.json"
        export_path = temp / "exports"
        export_path.mkdir()

        consent_path.write_text(json.dumps(deepcopy(DEFAULT_CONSENT_STORE), indent=2), encoding="utf-8")
        sharing_path.write_text(json.dumps(deepcopy(DEFAULT_SHARING_STORE), indent=2), encoding="utf-8")
        rights_path.write_text(json.dumps(deepcopy(DEFAULT_RIGHTS_REQUEST_STORE), indent=2), encoding="utf-8")
        access_log_path.write_text("[]", encoding="utf-8")

        # Configure handler
        ParcelPlatformRequestHandler.consent_store_path = consent_path
        ParcelPlatformRequestHandler.sharing_store_path = sharing_path
        ParcelPlatformRequestHandler.rights_store_path = rights_path
        ParcelPlatformRequestHandler.access_log_path = access_log_path
        ParcelPlatformRequestHandler.export_dir_path = export_path
        ParcelPlatformRequestHandler.allowed_input_roots = [temp]

        # Start server on random port
        server = ThreadingHTTPServer(("127.0.0.1", 0), ParcelPlatformRequestHandler)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            # Test 1: Health endpoint
            status, body = _get_json(f"{base}/v1/parcel-platform/health")
            assert status == 200 and body.get("ok"), f"health check failed: {status} {body}"
            print("  PASS health endpoint")

            # Test 2: Consent grant without notice → rejected
            status, body = _post_json(f"{base}/v1/parcels/parcel_001/consents", {
                "sharing_scope": "neighborhood_pm25",
                "data_classes": ["outdoor_pm25"],
                "custody_tier": "shared",
                "recipient_type": "neighborhood_pool",
            })
            assert status == 400, f"expected 400 for consent without notice, got {status}"
            assert "notice" in body.get("detail", "").lower(), f"expected notice error, got: {body}"
            print("  PASS consent without notice rejected (400)")

            # Test 3: Consent grant with structurally private data → rejected
            status, body = _post_json(f"{base}/v1/parcels/parcel_001/consents", {
                "sharing_scope": "neighborhood_pm25",
                "data_classes": ["indoor_pm25"],
                "custody_tier": "shared",
                "recipient_type": "neighborhood_pool",
                "notice_acknowledged": True,
            })
            assert status == 400, f"expected 400 for private data class, got {status}"
            assert "structurally private" in body.get("detail", "").lower(), f"expected private error, got: {body}"
            print("  PASS structurally private data class rejected (400)")

            # Test 4: Valid consent grant with notice → 201
            status, body = _post_json(f"{base}/v1/parcels/parcel_001/consents", {
                "sharing_scope": "neighborhood_pm25",
                "data_classes": ["outdoor_pm25"],
                "custody_tier": "shared",
                "recipient_type": "neighborhood_pool",
                "temporal_resolution": "hourly",
                "spatial_precision": "parcel",
                "notice_acknowledged": True,
                "notice_acknowledged_at": "2026-04-15T00:00:00Z",
            })
            assert status == 201, f"expected 201 for valid consent, got {status}: {body}"
            consent = body.get("consent", {})
            consent_id = consent.get("consent_id")
            assert consent_id, f"missing consent_id in response: {body}"
            assert consent.get("notice_acknowledged_at") == "2026-04-15T00:00:00Z"
            print("  PASS valid consent granted (201)")

            # Test 5: Governance status shows the consent
            status, body = _get_json(f"{base}/v1/parcels/parcel_001/governance/status")
            assert status == 200, f"expected 200 for governance status, got {status}"
            gov_status = body.get("status", {})
            currently_sharing = gov_status.get("currently_sharing", [])
            found = any(c.get("consent_id") == consent_id for c in currently_sharing)
            assert found, f"consent {consent_id} not in governance status: {currently_sharing}"
            print("  PASS governance status reflects consent")

            # Test 6: Revoke consent → 200
            status, body = _post_json(
                f"{base}/v1/parcels/parcel_001/consents/{consent_id}/revoke",
                {"reason": "http_governance_test"},
            )
            assert status == 200, f"expected 200 for revocation, got {status}: {body}"
            assert body.get("revoked"), f"expected revoked=true: {body}"
            print("  PASS consent revoked (200)")

            # Test 7: Governance status no longer shows the consent as active
            status, body = _get_json(f"{base}/v1/parcels/parcel_001/governance/status")
            assert status == 200
            gov_status = body.get("status", {})
            currently_sharing = gov_status.get("currently_sharing", [])
            still_active = any(c.get("consent_id") == consent_id for c in currently_sharing)
            assert not still_active, f"revoked consent still active in status: {currently_sharing}"
            print("  PASS revoked consent removed from active sharing")

            # Test 8: Access log records all governance operations
            log = json.loads(access_log_path.read_text(encoding="utf-8"))
            actions = [entry.get("action") for entry in log]
            assert "grant_consent" in actions, f"access log missing grant_consent: {actions}"
            assert "revoke_consent" in actions, f"access log missing revoke_consent: {actions}"
            print("  PASS access log records governance operations")

        finally:
            server.shutdown()

    print("PASS oesis.checks v1.0 HTTP governance (8 tests)")


if __name__ == "__main__":
    main()
