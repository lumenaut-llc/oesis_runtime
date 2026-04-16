"""Offline acceptance test for ingest authorization (DA-3, V1-G2).

Tests the authorize_ingest_request function directly without spinning up
an HTTP server. Validates:
- Auth disabled (no API key, no registry) → all requests pass
- API key validation (correct, wrong, missing)
- Node identity validation (registered, unregistered, missing header)
- Combined checks
"""

from __future__ import annotations

from oesis.ingest.v1_0.auth import AuthResult, authorize_ingest_request


class _FakeHeaders(dict):
    """Minimal dict-like that supports .get() for testing."""
    pass


SAMPLE_REGISTRY = {
    "parcel_id": "parcel_demo_001",
    "nodes": [
        {"node_id": "bench-air-01", "status": "active"},
        {"node_id": "mast-lite-01", "status": "active"},
        {"node_id": "flood-node-01", "status": "active"},
    ],
}

TEST_API_KEY = "test-secret-key-for-acceptance"


def _headers(**kwargs) -> _FakeHeaders:
    return _FakeHeaders(kwargs)


def test_no_auth_configured():
    """With no API key and no registry, all requests are authorized."""
    result = authorize_ingest_request(_headers())
    assert result.authorized, f"expected authorized, got: {result}"


def test_api_key_correct():
    """Correct Bearer token passes."""
    result = authorize_ingest_request(
        _headers(Authorization=f"Bearer {TEST_API_KEY}"),
        api_key=TEST_API_KEY,
    )
    assert result.authorized, f"expected authorized, got: {result}"


def test_api_key_wrong():
    """Wrong Bearer token is rejected."""
    result = authorize_ingest_request(
        _headers(Authorization="Bearer wrong-key"),
        api_key=TEST_API_KEY,
    )
    assert not result.authorized, "expected rejection for wrong key"
    assert "invalid API key" in (result.rejection_reason or "")


def test_api_key_missing():
    """Missing Authorization header is rejected when API key is configured."""
    result = authorize_ingest_request(
        _headers(),
        api_key=TEST_API_KEY,
    )
    assert not result.authorized, "expected rejection for missing auth header"
    assert "missing" in (result.rejection_reason or "").lower()


def test_api_key_malformed():
    """Non-Bearer Authorization header is rejected."""
    result = authorize_ingest_request(
        _headers(Authorization="Basic dXNlcjpwYXNz"),
        api_key=TEST_API_KEY,
    )
    assert not result.authorized, "expected rejection for malformed auth"


def test_node_registered():
    """Registered node ID passes."""
    result = authorize_ingest_request(
        _headers(**{"X-OESIS-Node-Id": "bench-air-01"}),
        registry=SAMPLE_REGISTRY,
    )
    assert result.authorized, f"expected authorized, got: {result}"
    assert result.node_id == "bench-air-01"


def test_node_unregistered():
    """Unregistered node ID is rejected."""
    result = authorize_ingest_request(
        _headers(**{"X-OESIS-Node-Id": "unknown-node-99"}),
        registry=SAMPLE_REGISTRY,
    )
    assert not result.authorized, "expected rejection for unregistered node"
    assert "not registered" in (result.rejection_reason or "")


def test_node_header_missing():
    """Missing X-OESIS-Node-Id header is rejected when registry is configured."""
    result = authorize_ingest_request(
        _headers(),
        registry=SAMPLE_REGISTRY,
    )
    assert not result.authorized, "expected rejection for missing node header"
    assert "missing" in (result.rejection_reason or "").lower()


def test_combined_auth():
    """Both API key and node identity must pass together."""
    # Both correct
    result = authorize_ingest_request(
        _headers(
            Authorization=f"Bearer {TEST_API_KEY}",
            **{"X-OESIS-Node-Id": "mast-lite-01"},
        ),
        api_key=TEST_API_KEY,
        registry=SAMPLE_REGISTRY,
    )
    assert result.authorized, f"expected authorized, got: {result}"
    assert result.node_id == "mast-lite-01"

    # Good key, bad node
    result = authorize_ingest_request(
        _headers(
            Authorization=f"Bearer {TEST_API_KEY}",
            **{"X-OESIS-Node-Id": "unknown-node"},
        ),
        api_key=TEST_API_KEY,
        registry=SAMPLE_REGISTRY,
    )
    assert not result.authorized, "expected rejection: good key but bad node"

    # Bad key, good node — key checked first, so key rejection
    result = authorize_ingest_request(
        _headers(
            Authorization="Bearer wrong",
            **{"X-OESIS-Node-Id": "bench-air-01"},
        ),
        api_key=TEST_API_KEY,
        registry=SAMPLE_REGISTRY,
    )
    assert not result.authorized, "expected rejection: bad key"
    assert "invalid API key" in (result.rejection_reason or "")


def test_node_id_passthrough_without_registry():
    """Without registry, X-OESIS-Node-Id is passed through but not validated."""
    result = authorize_ingest_request(
        _headers(**{"X-OESIS-Node-Id": "any-node"}),
    )
    assert result.authorized
    assert result.node_id == "any-node"


def main():
    tests = [
        test_no_auth_configured,
        test_api_key_correct,
        test_api_key_wrong,
        test_api_key_missing,
        test_api_key_malformed,
        test_node_registered,
        test_node_unregistered,
        test_node_header_missing,
        test_combined_auth,
        test_node_id_passthrough_without_registry,
    ]
    for test in tests:
        test()
        print(f"  PASS {test.__name__}")
    print(f"PASS oesis.checks v1.0 auth ({len(tests)} tests)")


if __name__ == "__main__":
    main()
