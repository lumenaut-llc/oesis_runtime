"""Node registry lifecycle for v1.0: extends v0.4 with metadata capture (PU-5, V1-G7).

Adds update_node_metadata() for structured installation metadata that feeds
the trust scoring install_quality factor.
"""

from __future__ import annotations

import json
import os
import tempfile
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
    """Check that a node is active and in the registry.

    Returns the node entry if valid, raises RegistryError otherwise.
    """
    nodes = {n["node_id"]: n for n in registry.get("nodes", [])}
    if node_id not in nodes:
        raise RegistryError(f"node {node_id} not found in registry")
    node = nodes[node_id]
    status = node.get("status", "unknown")
    if status not in ("active", "provisioning"):
        raise RegistryError(f"node {node_id} has non-active status: {status}")
    return node


def filter_active_nodes(registry: dict) -> list[dict]:
    """Return only active nodes."""
    return [
        node for node in registry.get("nodes", [])
        if node.get("status") == "active"
    ]


def bind_observation_to_registry(normalized: dict, registry: dict) -> dict:
    """Enrich a normalized observation with registry metadata."""
    node_id = normalized.get("node_id")
    nodes = {n["node_id"]: n for n in registry.get("nodes", [])}
    if node_id not in nodes:
        return normalized

    node = nodes[node_id]
    enriched = dict(normalized)
    provenance = dict(enriched.get("provenance", {}))
    install_meta = node.get("installation_metadata", {})
    provenance["registry_metadata"] = {
        "node_family": node.get("node_family"),
        "calibration_state": install_meta.get("calibration_state", "provisional"),
        "install_status": install_meta.get("install_status", "provisional"),
        "location_mode": node.get("location_mode"),
    }
    enriched["provenance"] = provenance
    return enriched


REQUIRED_METADATA_FIELDS = ("location_type", "mount_type", "install_date")
OPTIONAL_METADATA_FIELDS = (
    "orientation",
    "shelter_details",
    "installer_notes",
    "install_height_cm",
    "sun_exposure_class",
    "airflow_exposure_class",
    "calibration_state",
    "install_status",
)


def _atomic_write_json(path: Path, payload):
    """Write JSON atomically via temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def update_node_metadata(
    registry_path: str | Path,
    node_id: str,
    metadata: dict,
) -> dict:
    """Update installation metadata for a node in the registry.

    Required fields: location_type, mount_type, install_date
    Optional fields: orientation, shelter_details, installer_notes,
        install_height_cm, sun_exposure_class, airflow_exposure_class,
        calibration_state, install_status

    Returns the updated node entry.
    """
    path = Path(registry_path)
    registry = load_node_registry(path)

    # Find the node
    node_entry = None
    for node in registry.get("nodes", []):
        if node.get("node_id") == node_id:
            node_entry = node
            break
    if node_entry is None:
        raise RegistryError(f"node {node_id} not found in registry")

    # Validate required fields
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            raise RegistryError(f"missing required metadata field: {field}")

    # Build clean metadata dict
    clean_metadata = {}
    for field in REQUIRED_METADATA_FIELDS:
        clean_metadata[field] = metadata[field]
    for field in OPTIONAL_METADATA_FIELDS:
        if field in metadata:
            clean_metadata[field] = metadata[field]

    # Merge into existing metadata
    existing = node_entry.get("installation_metadata", {})
    existing.update(clean_metadata)
    existing["updated_at"] = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    node_entry["installation_metadata"] = existing

    # Update registry timestamp
    registry["updated_at"] = existing["updated_at"]

    # Write back atomically
    _atomic_write_json(path, registry)

    return dict(node_entry)
