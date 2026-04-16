"""Ingest API authorization for v1.0 Tier B.

Opt-in via environment variables:
- OESIS_INGEST_API_KEY: shared secret for API key validation
- OESIS_NODE_REGISTRY_PATH: path to node-registry JSON for node identity checks

When neither is set, all requests are authorized (backward compatible with
Tier A bench testing).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass


@dataclass
class AuthResult:
    """Result of an authorization check."""
    authorized: bool
    node_id: str | None = None
    rejection_reason: str | None = None


def _check_api_key(headers, *, required_key: str | None) -> tuple[bool, str | None]:
    """Validate Bearer token against required API key.

    Returns (True, None) if valid or auth disabled, (False, reason) if rejected.
    """
    if required_key is None:
        return True, None

    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "missing or malformed Authorization header (expected Bearer token)"

    provided_key = auth_header[len("Bearer "):]
    if not hmac.compare_digest(provided_key, required_key):
        return False, "invalid API key"

    return True, None


def _check_node_identity(headers, *, registry: dict | None) -> tuple[bool, str | None, str | None]:
    """Validate X-OESIS-Node-Id against registered nodes.

    Returns (True, None, node_id) if valid or registry not loaded,
    (False, reason, None) if rejected.
    """
    if registry is None:
        return True, None, headers.get("X-OESIS-Node-Id")

    node_id = headers.get("X-OESIS-Node-Id")
    if not node_id:
        return False, "missing X-OESIS-Node-Id header", None

    nodes = registry.get("nodes", [])
    registered_ids = {
        node.get("node_id") for node in nodes if isinstance(node, dict)
    }

    if node_id not in registered_ids:
        return False, f"node not registered: {node_id}", None

    return True, None, node_id


def authorize_ingest_request(
    headers,
    *,
    api_key: str | None = None,
    registry: dict | None = None,
) -> AuthResult:
    """Authorize an ingest API request.

    Checks API key first, then node identity. Both are opt-in:
    - api_key=None → API key check skipped
    - registry=None → node identity check skipped
    - Both None → all requests authorized (Tier A mode)
    """
    key_ok, key_reason = _check_api_key(headers, required_key=api_key)
    if not key_ok:
        return AuthResult(authorized=False, rejection_reason=key_reason)

    node_ok, node_reason, node_id = _check_node_identity(headers, registry=registry)
    if not node_ok:
        return AuthResult(authorized=False, rejection_reason=node_reason)

    return AuthResult(authorized=True, node_id=node_id)
