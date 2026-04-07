import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "oesis"
ASSETS_DIR = PACKAGE_ROOT / "assets"
EXAMPLES_DIR = ASSETS_DIR / "examples"
INFERENCE_CONFIG_ROOT = ASSETS_DIR / "config" / "inference"

_contracts_bundle_dir = os.environ.get("OESIS_CONTRACTS_BUNDLE_DIR")
if _contracts_bundle_dir:
    bundle_examples_dir = Path(_contracts_bundle_dir).expanduser().resolve() / "examples"
    EXAMPLES_DIR = bundle_examples_dir if bundle_examples_dir.is_dir() else EXAMPLES_DIR

_inference_config_dir = os.environ.get("OESIS_INFERENCE_CONFIG_DIR")
if _inference_config_dir:
    INFERENCE_CONFIG_DIR = Path(_inference_config_dir).expanduser().resolve()
else:
    INFERENCE_CONFIG_DIR = INFERENCE_CONFIG_ROOT

# Backward-compatible aliases while the runtime finishes decoupling from old docs-era names.
RUNTIME_ROOT = PACKAGE_ROOT
RUNTIME_ASSETS_DIR = ASSETS_DIR
RUNTIME_EXAMPLES_DIR = EXAMPLES_DIR
RUNTIME_INFERENCE_CONFIG_DIR = INFERENCE_CONFIG_ROOT
DOCS_EXAMPLES_DIR = EXAMPLES_DIR
