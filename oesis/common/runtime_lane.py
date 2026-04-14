"""Materialize explicit runtime asset lanes without mutating default paths.

The current runtime intentionally supports only a frozen default `v0.1` lane and
one additive future lane. Generalize this only after a second accepted pre-1.0
slice is real enough to justify more versioned runtime surfaces.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

from oesis.common.repo_paths import ASSETS_DIR

DEFAULT_LANE = "v0.1"
RUNTIME_LANE_ENV_VAR = "OESIS_RUNTIME_LANE"
RUNTIME_LANE_HEADER = "X-OESIS-Lane"

DEFAULT_EXAMPLES_ROOT = ASSETS_DIR / DEFAULT_LANE / "examples"
DEFAULT_INFERENCE_CONFIG_ROOT = ASSETS_DIR / DEFAULT_LANE / "config" / "inference"
LANE_DIR_PATTERN = re.compile(r"^v\d+\.\d+$")


def discover_supported_lanes() -> set[str]:
    lanes = {DEFAULT_LANE}
    if not ASSETS_DIR.exists():
        return lanes
    for child in ASSETS_DIR.iterdir():
        if not child.is_dir():
            continue
        if not LANE_DIR_PATTERN.match(child.name):
            continue
        has_examples = (child / "examples").is_dir()
        has_config = (child / "config" / "inference").is_dir()
        if has_examples or has_config:
            lanes.add(child.name)
    return lanes


SUPPORTED_LANES = discover_supported_lanes()


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def overlay_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def copy_root_files(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(src_dir.iterdir()):
        if src.is_file():
            shutil.copy2(src, dst_dir / src.name)


def normalize_lane(lane: str) -> str:
    if lane not in SUPPORTED_LANES:
        raise SystemExit(f"unsupported runtime lane: {lane}")
    return lane


def requested_lane_from_headers(headers) -> str | None:
    if headers is None:
        return None
    lane = headers.get(RUNTIME_LANE_HEADER)
    return lane if lane else None


def resolve_runtime_lane(preferred_lane: str | None = None) -> str:
    lane = preferred_lane or os.environ.get(RUNTIME_LANE_ENV_VAR) or DEFAULT_LANE
    if lane not in SUPPORTED_LANES:
        raise SystemExit(f"unsupported runtime lane: {lane}")
    return lane


def lane_examples_override_root(lane: str) -> Path:
    lane = normalize_lane(lane)
    return ASSETS_DIR / lane / "examples"


def lane_inference_override_root(lane: str) -> Path:
    lane = normalize_lane(lane)
    return ASSETS_DIR / lane / "config" / "inference"


def versioning_payload(*, lane: str, api_version: str = "v1") -> dict:
    resolved = resolve_runtime_lane(lane)
    return {
        "api_version": api_version,
        "runtime_lane": resolved,
        "default_lane": DEFAULT_LANE,
        "supported_lanes": sorted(SUPPORTED_LANES),
    }


def materialize_contracts_bundle(destination: Path, *, lane: str) -> Path:
    lane = resolve_runtime_lane(lane)
    ensure_clean_dir(destination)
    examples_dst = destination / "examples"
    shutil.copytree(DEFAULT_EXAMPLES_ROOT, examples_dst, dirs_exist_ok=False)
    if lane != DEFAULT_LANE:
        overlay_tree(lane_examples_override_root(lane), examples_dst)
    return destination


def materialize_inference_config(destination: Path, *, lane: str) -> Path:
    lane = resolve_runtime_lane(lane)
    ensure_clean_dir(destination)
    copy_root_files(DEFAULT_INFERENCE_CONFIG_ROOT, destination)
    if lane != DEFAULT_LANE:
        overlay_tree(lane_inference_override_root(lane), destination)
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize explicit runtime asset lanes for OESIS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    contracts = subparsers.add_parser(
        "contracts-bundle",
        help="Prepare a contracts-bundle-style examples directory for a lane.",
    )
    contracts.add_argument("--lane", default=DEFAULT_LANE, choices=sorted(SUPPORTED_LANES))
    contracts.add_argument("--destination", required=True)

    config = subparsers.add_parser(
        "inference-config",
        help="Prepare an inference config directory for a lane.",
    )
    config.add_argument("--lane", default=DEFAULT_LANE, choices=sorted(SUPPORTED_LANES))
    config.add_argument("--destination", required=True)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = Path(args.destination).resolve()
    if args.command == "contracts-bundle":
        print(materialize_contracts_bundle(destination, lane=args.lane))
        return 0
    if args.command == "inference-config":
        print(materialize_inference_config(destination, lane=args.lane))
        return 0
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
