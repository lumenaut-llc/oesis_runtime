"""Offline acceptance: build reference flow and verify artifact shapes."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
from pathlib import Path

from oesis.common.runtime_lane import (
    DEFAULT_LANE,
    RUNTIME_LANE_ENV_VAR,
    SUPPORTED_LANES,
    materialize_contracts_bundle,
    materialize_inference_config,
    resolve_runtime_lane,
)

_LANE_TO_MODULE = {
    "v0.1": ("oesis.checks.v0_1.acceptance", "build_v01_runtime_flow"),
    "v0.2": ("oesis.checks.v0_2.acceptance", "build_v02_runtime_flow"),
    "v0.3": ("oesis.checks.v0_3.acceptance", "build_v03_runtime_flow"),
    "v0.4": ("oesis.checks.v0_4.acceptance", "build_v04_runtime_flow"),
    "v0.5": ("oesis.checks.v0_5.acceptance", "build_v05_runtime_flow"),
    "v1.0": ("oesis.checks.v1_0.acceptance", "build_v10_runtime_flow"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m oesis.checks",
        description="Run offline acceptance checks for the active runtime lane.",
    )
    parser.add_argument(
        "--lane",
        default=None,
        choices=sorted(SUPPORTED_LANES),
        help="Runtime lane to check (default: OESIS_RUNTIME_LANE or v0.1).",
    )
    return parser.parse_args()


def _setup_lane_env(lane: str, tmpdir: str) -> None:
    """Materialize lane assets and set env vars before any loader imports."""
    os.environ[RUNTIME_LANE_ENV_VAR] = lane
    if lane == DEFAULT_LANE:
        return
    bundle_dir = os.path.join(tmpdir, "contracts-bundle")
    config_dir = os.path.join(tmpdir, "inference-config")
    materialize_contracts_bundle(Path(bundle_dir), lane=lane)
    materialize_inference_config(Path(config_dir), lane=lane)
    os.environ["OESIS_CONTRACTS_BUNDLE_DIR"] = bundle_dir
    os.environ["OESIS_INFERENCE_CONFIG_DIR"] = config_dir


def main() -> int:
    args = parse_args()
    lane = resolve_runtime_lane(args.lane)

    with tempfile.TemporaryDirectory(prefix="oesis-checks-") as tmpdir:
        _setup_lane_env(lane, tmpdir)

        # Evict cached modules so fresh imports see the new env vars.
        # The chain is: v0_1.repo_paths → repo_paths → context loader → acceptance.
        mod_name, builder_name = _LANE_TO_MODULE.get(lane, _LANE_TO_MODULE["v0.1"])
        lane_tag = lane.replace(".", "_")
        evict = [
            "oesis.common.v0_1.repo_paths",
            "oesis.common.v1_0.repo_paths",
            "oesis.common.repo_paths",
            f"oesis.context.{lane_tag}.loader",
            mod_name,
        ]
        for name in evict:
            sys.modules.pop(name, None)

        mod = importlib.import_module(mod_name)

        builder = getattr(mod, builder_name)
        payload = builder(computed_at="2026-03-30T19:46:00Z")
        mod.verify_runtime_flow_artifacts(payload)
        print(f"PASS oesis.checks {payload['normalized_observation']['versioning']['runtime_lane']} offline")

    return 0


if __name__ == "__main__":
    sys.exit(main())
