"""Materialize explicit runtime asset lanes without mutating default paths.

The current runtime intentionally supports only a frozen default `v0.1` lane and
one additive future lane. Generalize this only after a second accepted pre-1.0
slice is real enough to justify more versioned runtime surfaces.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from oesis.common.repo_paths import ASSETS_DIR

DEFAULT_LANE = "v0.1"
SUPPORTED_LANES = {DEFAULT_LANE, "v1.0"}

DEFAULT_EXAMPLES_ROOT = ASSETS_DIR / "examples"
DEFAULT_INFERENCE_CONFIG_ROOT = ASSETS_DIR / "config" / "inference"
V10_EXAMPLES_ROOT = ASSETS_DIR / "v1.0" / "examples"
V10_INFERENCE_CONFIG_ROOT = ASSETS_DIR / "v1.0" / "config" / "inference"


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


def materialize_contracts_bundle(destination: Path, *, lane: str) -> Path:
    lane = normalize_lane(lane)
    ensure_clean_dir(destination)
    examples_dst = destination / "examples"
    shutil.copytree(DEFAULT_EXAMPLES_ROOT, examples_dst, dirs_exist_ok=False)
    if lane == "v1.0":
        overlay_tree(V10_EXAMPLES_ROOT, examples_dst)
    return destination


def materialize_inference_config(destination: Path, *, lane: str) -> Path:
    lane = normalize_lane(lane)
    ensure_clean_dir(destination)
    copy_root_files(DEFAULT_INFERENCE_CONFIG_ROOT, destination)
    if lane == "v1.0":
        overlay_tree(V10_INFERENCE_CONFIG_ROOT, destination)
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
    contracts.add_argument("--lane", default="v1.0", choices=sorted(SUPPORTED_LANES))
    contracts.add_argument("--destination", required=True)

    config = subparsers.add_parser(
        "inference-config",
        help="Prepare an inference config directory for a lane.",
    )
    config.add_argument("--lane", default="v1.0", choices=sorted(SUPPORTED_LANES))
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
