import os
from importlib import import_module


def _lane_module():
    lane = os.environ.get("OESIS_RUNTIME_LANE", "v0.1")
    module_name = "oesis.common.v1_0.repo_paths" if lane == "v1.0" else "oesis.common.v0_1.repo_paths"
    return import_module(module_name)


_lane = _lane_module()

REPO_ROOT = _lane.REPO_ROOT
PACKAGE_ROOT = _lane.PACKAGE_ROOT
ASSETS_DIR = _lane.ASSETS_DIR
ASSETS_BASELINE_DIR = _lane.ASSETS_BASELINE_DIR
EXAMPLES_DIR = _lane.EXAMPLES_DIR
INFERENCE_CONFIG_ROOT = _lane.INFERENCE_CONFIG_ROOT
INFERENCE_CONFIG_DIR = _lane.INFERENCE_CONFIG_DIR
RUNTIME_ROOT = _lane.RUNTIME_ROOT
RUNTIME_ASSETS_DIR = _lane.RUNTIME_ASSETS_DIR
RUNTIME_EXAMPLES_DIR = _lane.RUNTIME_EXAMPLES_DIR
RUNTIME_INFERENCE_CONFIG_DIR = _lane.RUNTIME_INFERENCE_CONFIG_DIR
DOCS_EXAMPLES_DIR = _lane.DOCS_EXAMPLES_DIR
