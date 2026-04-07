"""Offline v0.1 acceptance: build reference flow and verify artifact shapes."""

from __future__ import annotations

from .v01 import build_v01_runtime_flow, verify_runtime_flow_artifacts


def main() -> None:
    payload = build_v01_runtime_flow()
    verify_runtime_flow_artifacts(payload)
    print("PASS oesis.checks v0.1 offline")


if __name__ == "__main__":
    main()
