"""Node registry lifecycle for v0.4: load, validate, filter, and bind."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class RegistryError(Exception):
    pass


def load_node_registry(path: str | Path) -> dict:
    """Load a node registry JSON file."""
    p = Path(path)
    if not p.exists():
        raise RegistryError(f"registry file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def validate_node_lifecycle(registry: dict, node_id: str) -> dict:
    """Check that a node is enabled and has acceptable calibration.

    Returns the node entry if valid, raises RegistryError otherwise.
    """
    nodes = {n["node_id"]: n for n in registry.get("nodes", [])}
    if node_id not in nodes:
        raise RegistryError(f"node {node_id} not found in registry")
    node = nodes[node_id]
    if not node.get("enabled", False):
        raise RegistryError(f"node {node_id} is disabled in registry")
    cal = node.get("calibration_state", "unknown")
    if cal not in ("provisional", "verified", "recently_calibrated"):
        raise RegistryError(f"node {node_id} calibration unacceptable: {cal}")
    return node


def filter_active_nodes(registry: dict, *, reference_time: str | None = None) -> list[dict]:
    """Return only enabled nodes with acceptable calibration state."""
    active = []
    for node in registry.get("nodes", []):
        if not node.get("enabled", False):
            continue
        cal = node.get("calibration_state", "unknown")
        if cal not in ("provisional", "verified", "recently_calibrated"):
            continue
        active.append(node)
    return active


def bind_observation_to_registry(normalized: dict, registry: dict) -> dict:
    """Enrich a normalized observation with registry metadata.

    Adds hardware_family, calibration_state, and install_role from the registry
    into the observation's provenance.
    """
    node_id = normalized.get("node_id")
    nodes = {n["node_id"]: n for n in registry.get("nodes", [])}
    if node_id not in nodes:
        return normalized

    node = nodes[node_id]
    enriched = dict(normalized)
    provenance = dict(enriched.get("provenance", {}))
    provenance["registry_metadata"] = {
        "hardware_family": node.get("hardware_family"),
        "calibration_state": node.get("calibration_state"),
        "install_role": node.get("install_role"),
        "location_mode": node.get("location_mode"),
    }
    enriched["provenance"] = provenance
    return enriched
