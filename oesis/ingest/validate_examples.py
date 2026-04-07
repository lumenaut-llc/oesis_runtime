#!/usr/bin/env python3

import json
import sys
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR

EXAMPLES_DIR = DOCS_EXAMPLES_DIR


class ValidationError(Exception):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path.name}: invalid JSON: {exc}") from exc


def require(condition: bool, message: str):
    if not condition:
        raise ValidationError(message)


def require_type(value, expected_type, field_name: str):
    require(isinstance(value, expected_type), f"{field_name}: expected {expected_type.__name__}")


def require_number(value, field_name: str, minimum=None, maximum=None, exclusive_minimum=None):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{field_name}: expected number")
    if minimum is not None:
      require(value >= minimum, f"{field_name}: expected >= {minimum}")
    if maximum is not None:
      require(value <= maximum, f"{field_name}: expected <= {maximum}")
    if exclusive_minimum is not None:
      require(value > exclusive_minimum, f"{field_name}: expected > {exclusive_minimum}")


def validate_node_observation(payload):
    required = [
        "schema_version",
        "node_id",
        "observed_at",
        "firmware_version",
        "location_mode",
        "sensors",
        "health",
    ]
    for field in required:
        require(field in payload, f"node observation missing required field: {field}")

    require(payload["schema_version"] == "oesis.bench-air.v1", "schema_version must be oesis.bench-air.v1")
    require_type(payload["node_id"], str, "node_id")
    require_type(payload["observed_at"], str, "observed_at")
    require(payload["location_mode"] in {"indoor", "sheltered", "outdoor"}, "location_mode invalid")

    sensors = payload["sensors"]
    require_type(sensors, dict, "sensors")
    for sensor_name in ("sht45", "bme680"):
        require(sensor_name in sensors, f"sensors missing {sensor_name}")

    sht45 = sensors["sht45"]
    require_type(sht45, dict, "sensors.sht45")
    require_type(sht45["present"], bool, "sensors.sht45.present")
    require_number(sht45["temperature_c"], "sensors.sht45.temperature_c")
    require_number(sht45["relative_humidity_pct"], "sensors.sht45.relative_humidity_pct", 0, 100)

    bme680 = sensors["bme680"]
    require_type(bme680, dict, "sensors.bme680")
    require_type(bme680["present"], bool, "sensors.bme680.present")
    require_number(bme680["temperature_c"], "sensors.bme680.temperature_c")
    require_number(bme680["relative_humidity_pct"], "sensors.bme680.relative_humidity_pct", 0, 100)
    require_number(bme680["pressure_hpa"], "sensors.bme680.pressure_hpa")
    require_number(bme680["gas_resistance_ohm"], "sensors.bme680.gas_resistance_ohm", exclusive_minimum=0)

    health = payload["health"]
    require_type(health, dict, "health")
    require_number(health["uptime_s"], "health.uptime_s", minimum=0)
    require_type(health["wifi_connected"], bool, "health.wifi_connected")
    require_number(health["free_heap_bytes"], "health.free_heap_bytes", minimum=0)
    require_number(health["read_failures_total"], "health.read_failures_total", minimum=0)
    require(isinstance(health["last_error"], (str, type(None))), "health.last_error: expected string or null")


def validate_parcel_state(payload):
    required = [
        "parcel_id",
        "computed_at",
        "shelter_status",
        "reentry_status",
        "egress_status",
        "asset_risk_status",
        "confidence",
        "evidence_mode",
        "inference_basis",
        "explanation_payload",
        "reasons",
        "hazards",
        "freshness",
        "provenance_summary",
    ]
    for field in required:
        require(field in payload, f"parcel state missing required field: {field}")

    statuses = {"safe", "caution", "unsafe", "unknown"}
    for field in ("shelter_status", "reentry_status", "egress_status", "asset_risk_status"):
        require(payload[field] in statuses, f"{field}: invalid status")

    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["computed_at"], str, "computed_at")
    require_number(payload["confidence"], "confidence", minimum=0, maximum=1)
    require(
        payload["evidence_mode"] in {"local_only", "local_plus_public", "public_only", "insufficient"},
        "evidence_mode invalid",
    )
    require(
        payload["inference_basis"] in {
            "local_only",
            "local_plus_shared",
            "local_plus_public",
            "local_plus_shared_plus_public",
            "public_only",
            "shared_only",
            "shared_plus_public",
            "insufficient",
        },
        "inference_basis invalid",
    )

    reasons = payload["reasons"]
    require_type(reasons, list, "reasons")
    require(len(reasons) > 0, "reasons must not be empty")
    for i, reason in enumerate(reasons):
        require_type(reason, str, f"reasons[{i}]")
        require(reason.strip() != "", f"reasons[{i}] must not be blank")

    explanation = payload["explanation_payload"]
    require_type(explanation, dict, "explanation_payload")
    require_type(explanation["headline"], str, "explanation_payload.headline")
    basis = explanation["basis"]
    require_type(basis, dict, "explanation_payload.basis")
    require_type(basis["evidence_mode"], str, "explanation_payload.basis.evidence_mode")
    require_type(basis["inference_basis"], str, "explanation_payload.basis.inference_basis")
    require(basis["confidence_band"] in {"low", "medium", "high"}, "explanation_payload.basis.confidence_band invalid")
    require_type(explanation["drivers"], list, "explanation_payload.drivers")
    require_type(explanation["limitations"], list, "explanation_payload.limitations")
    require_type(explanation["evidence_contributions"], list, "explanation_payload.evidence_contributions")
    for i, contribution in enumerate(explanation["evidence_contributions"]):
        require_type(contribution, dict, f"explanation_payload.evidence_contributions[{i}]")
        require_type(
            contribution["contribution_id"],
            str,
            f"explanation_payload.evidence_contributions[{i}].contribution_id",
        )
        require(
            contribution["source_class"] in {"local", "shared", "public", "parcel_context", "system"},
            f"explanation_payload.evidence_contributions[{i}].source_class invalid",
        )
        require_type(contribution["source_name"], str, f"explanation_payload.evidence_contributions[{i}].source_name")
        require(
            contribution["role"] in {"driver", "limitation"},
            f"explanation_payload.evidence_contributions[{i}].role invalid",
        )
        require_type(contribution["summary"], str, f"explanation_payload.evidence_contributions[{i}].summary")
        require_type(contribution["hazards"], list, f"explanation_payload.evidence_contributions[{i}].hazards")
        require_number(
            contribution["weight"],
            f"explanation_payload.evidence_contributions[{i}].weight",
            minimum=0,
            maximum=1,
        )
        require(
            contribution["visibility"] in {"homeowner_safe", "internal_only"},
            f"explanation_payload.evidence_contributions[{i}].visibility invalid",
        )
        if "freshness_band" in contribution:
            require(
                contribution["freshness_band"] in {"fresh", "aging", "stale", "expired"},
                f"explanation_payload.evidence_contributions[{i}].freshness_band invalid",
            )
    source_breakdown = explanation["source_breakdown"]
    require_type(source_breakdown, dict, "explanation_payload.source_breakdown")
    for field in ("local", "shared", "public", "parcel_context", "system"):
        require_type(source_breakdown[field], bool, f"explanation_payload.source_breakdown.{field}")

    hazards = payload["hazards"]
    require_type(hazards, dict, "hazards")
    for field in ("smoke_probability", "flood_probability", "heat_probability"):
        require_number(hazards[field], f"hazards.{field}", minimum=0, maximum=1)

    freshness = payload["freshness"]
    require_type(freshness, dict, "freshness")
    require_type(freshness["latest_observation_at"], str, "freshness.latest_observation_at")
    require_number(freshness["seconds_since_latest"], "freshness.seconds_since_latest", minimum=0)
    require_type(freshness["stale"], bool, "freshness.stale")

    provenance = payload["provenance_summary"]
    require_type(provenance, dict, "provenance_summary")
    require_number(provenance["observation_count"], "provenance_summary.observation_count", minimum=0)
    require_type(provenance["source_modes"], list, "provenance_summary.source_modes")
    require(len(provenance["source_modes"]) > 0, "provenance_summary.source_modes must not be empty")
    if "observation_refs" in provenance:
        require_type(provenance["observation_refs"], list, "provenance_summary.observation_refs")


def validate_public_context(payload):
    required = [
        "context_id",
        "source_kind",
        "source_name",
        "observed_at",
        "coverage_mode",
        "parcel_id",
        "hazards",
        "summary",
    ]
    for field in required:
        require(field in payload, f"public context missing required field: {field}")

    require_type(payload["context_id"], str, "context_id")
    require(payload["source_kind"] == "public_context", "source_kind must be public_context")
    require_type(payload["source_name"], str, "source_name")
    require_type(payload["observed_at"], str, "observed_at")
    require(payload["coverage_mode"] in {"regional", "subregional", "parcel_adjacent"}, "coverage_mode invalid")
    require_type(payload["parcel_id"], str, "parcel_id")

    hazards = payload["hazards"]
    require_type(hazards, dict, "hazards")
    for field in ("smoke_probability", "flood_probability", "heat_probability"):
        require_number(hazards[field], f"hazards.{field}", minimum=0, maximum=1)

    summary = payload["summary"]
    require_type(summary, list, "summary")
    require(len(summary) > 0, "summary must not be empty")
    for i, value in enumerate(summary):
        require_type(value, str, f"summary[{i}]")
        require(value.strip() != "", f"summary[{i}] must not be blank")


def validate_parcel_context(payload):
    required = ["parcel_id", "site_profile", "node_installations", "parcel_priors"]
    for field in required:
        require(field in payload, f"parcel context missing required field: {field}")

    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["site_profile"], dict, "site_profile")
    require_type(payload["node_installations"], list, "node_installations")
    require(len(payload["node_installations"]) > 0, "node_installations must not be empty")
    require_type(payload["parcel_priors"], dict, "parcel_priors")

    for i, installation in enumerate(payload["node_installations"]):
        require_type(installation, dict, f"node_installations[{i}]")
        for field in (
            "node_id",
            "node_type",
            "location_mode",
            "install_role",
            "placement_notes",
            "height_m",
            "exposure_bias_flags",
            "installed_at",
        ):
            require(field in installation, f"node_installations[{i}] missing required field: {field}")


def validate_evidence_summary(payload):
    required = [
        "parcel_id",
        "computed_at",
        "evidence_mode",
        "inference_basis",
        "confidence",
        "headline",
        "confidence_band",
        "top_drivers",
        "top_limitations",
        "source_breakdown",
        "grouped_contributions",
        "source_modes",
        "freshness",
    ]
    for field in required:
        require(field in payload, f"evidence summary missing required field: {field}")

    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["computed_at"], str, "computed_at")
    require_type(payload["evidence_mode"], str, "evidence_mode")
    require_type(payload["inference_basis"], str, "inference_basis")
    require_number(payload["confidence"], "confidence", minimum=0, maximum=1)
    require_type(payload["headline"], str, "headline")
    require(payload["confidence_band"] in {"low", "medium", "high"}, "confidence_band invalid")
    require_type(payload["top_drivers"], list, "top_drivers")
    require_type(payload["top_limitations"], list, "top_limitations")
    require_type(payload["source_modes"], list, "source_modes")

    source_breakdown = payload["source_breakdown"]
    require_type(source_breakdown, dict, "source_breakdown")
    for field in ("local", "shared", "public", "parcel_context", "system"):
        require_type(source_breakdown[field], bool, f"source_breakdown.{field}")

    grouped = payload["grouped_contributions"]
    require_type(grouped, dict, "grouped_contributions")
    for field in ("local", "shared", "public", "parcel_context", "system"):
        require_type(grouped[field], list, f"grouped_contributions.{field}")
        for i, contribution in enumerate(grouped[field]):
            require_type(contribution, dict, f"grouped_contributions.{field}[{i}]")
            require_type(contribution["contribution_id"], str, f"grouped_contributions.{field}[{i}].contribution_id")
            require_type(contribution["summary"], str, f"grouped_contributions.{field}[{i}].summary")
            require_number(
                contribution["weight"],
                f"grouped_contributions.{field}[{i}].weight",
                minimum=0,
                maximum=1,
            )

    freshness = payload["freshness"]
    require_type(freshness, dict, "freshness")
    require_type(freshness["latest_observation_at"], str, "freshness.latest_observation_at")
    require_number(freshness["seconds_since_latest"], "freshness.seconds_since_latest", minimum=0)
    require_type(freshness["stale"], bool, "freshness.stale")


def validate_raw_public_weather(payload):
    required = [
        "source_name",
        "observed_at",
        "parcel_id",
        "regional_temperature_c",
        "regional_relative_humidity_pct",
        "advisories",
    ]
    for field in required:
        require(field in payload, f"raw public weather missing required field: {field}")

    require_type(payload["source_name"], str, "source_name")
    require_type(payload["observed_at"], str, "observed_at")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_number(payload["regional_temperature_c"], "regional_temperature_c")
    require_number(
        payload["regional_relative_humidity_pct"],
        "regional_relative_humidity_pct",
        minimum=0,
        maximum=100,
    )
    require_type(payload["advisories"], list, "advisories")


def validate_raw_public_smoke(payload):
    required = [
        "source_name",
        "observed_at",
        "parcel_id",
        "regional_pm25_ugm3",
        "smoke_advisory_level",
    ]
    for field in required:
        require(field in payload, f"raw public smoke missing required field: {field}")

    require_type(payload["source_name"], str, "source_name")
    require_type(payload["observed_at"], str, "observed_at")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_number(payload["regional_pm25_ugm3"], "regional_pm25_ugm3", minimum=0)
    require(
        payload["smoke_advisory_level"] in {"none", "light", "moderate", "heavy"},
        "smoke_advisory_level invalid",
    )


def validate_sharing_settings(payload):
    required = [
        "parcel_id",
        "updated_at",
        "private_only",
        "network_assist",
        "neighborhood_aggregate",
        "research_or_pilot",
        "notice_version",
        "revocation_pending",
    ]
    for field in required:
        require(field in payload, f"sharing settings missing required field: {field}")

    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["updated_at"], str, "updated_at")
    require_type(payload["private_only"], bool, "private_only")
    require_type(payload["network_assist"], bool, "network_assist")
    require_type(payload["neighborhood_aggregate"], bool, "neighborhood_aggregate")
    require_type(payload["research_or_pilot"], bool, "research_or_pilot")
    require_type(payload["notice_version"], str, "notice_version")
    require_type(payload["revocation_pending"], bool, "revocation_pending")


def validate_consent_record(payload):
    required = [
        "consent_record_id",
        "parcel_id",
        "account_id",
        "sharing_mode",
        "action",
        "effective_at",
        "notice_version",
        "source_surface",
    ]
    for field in required:
        require(field in payload, f"consent record missing required field: {field}")

    require_type(payload["consent_record_id"], str, "consent_record_id")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["account_id"], str, "account_id")
    require(payload["sharing_mode"] in {"network_assist", "neighborhood_aggregate", "research_or_pilot"}, "sharing_mode invalid")
    require(payload["action"] in {"enabled", "revoked"}, "action invalid")
    require_type(payload["effective_at"], str, "effective_at")
    require_type(payload["notice_version"], str, "notice_version")
    require_type(payload["source_surface"], str, "source_surface")


def validate_rights_request(payload):
    required = [
        "request_id",
        "parcel_id",
        "account_id",
        "request_type",
        "status",
        "created_at",
        "scope",
        "requested_from_surface",
    ]
    for field in required:
        require(field in payload, f"rights request missing required field: {field}")

    require_type(payload["request_id"], str, "request_id")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["account_id"], str, "account_id")
    require(payload["request_type"] in {"export", "delete"}, "request_type invalid")
    require(payload["status"] in {"submitted", "in_progress", "completed", "rejected"}, "status invalid")
    require_type(payload["created_at"], str, "created_at")
    require_type(payload["scope"], list, "scope")
    require(len(payload["scope"]) > 0, "scope must not be empty")
    valid_scope = {"private_parcel_data", "shared_data", "public_context", "derived_parcel_state", "administrative_record"}
    for i, value in enumerate(payload["scope"]):
        require(value in valid_scope, f"scope[{i}] invalid")
    require_type(payload["requested_from_surface"], str, "requested_from_surface")


def validate_shared_neighborhood_signal(payload):
    required = [
        "generated_at",
        "min_participants",
        "sharing_settings",
        "contributions",
    ]
    for field in required:
        require(field in payload, f"shared neighborhood signal missing required field: {field}")

    require_type(payload["generated_at"], str, "generated_at")
    require_number(payload["min_participants"], "min_participants", minimum=1)
    sharing_settings = payload["sharing_settings"]
    require_type(sharing_settings, list, "sharing_settings")
    sharing_refs = set()
    for i, entry in enumerate(sharing_settings):
        require_type(entry, dict, f"sharing_settings[{i}]")
        for field in ("parcel_ref", "neighborhood_aggregate", "revocation_pending"):
            require(field in entry, f"sharing_settings[{i}] missing required field: {field}")
        require_type(entry["parcel_ref"], str, f"sharing_settings[{i}].parcel_ref")
        require_type(entry["neighborhood_aggregate"], bool, f"sharing_settings[{i}].neighborhood_aggregate")
        require_type(entry["revocation_pending"], bool, f"sharing_settings[{i}].revocation_pending")
        sharing_refs.add(entry["parcel_ref"])
    contributions = payload["contributions"]
    require_type(contributions, list, "contributions")
    require(len(contributions) > 0, "contributions must not be empty")
    for i, contribution in enumerate(contributions):
        require_type(contribution, dict, f"contributions[{i}]")
        for field in ("cell_id", "source_class", "delayed_minutes", "hazards"):
            require(field in contribution, f"contributions[{i}] missing required field: {field}")
        require("parcel_id" not in contribution, f"contributions[{i}] must not include parcel_id")
        require_type(contribution["cell_id"], str, f"contributions[{i}].cell_id")
        require(contribution["source_class"] in {"shared_data", "public_context"}, f"contributions[{i}].source_class invalid")
        if contribution["source_class"] == "shared_data":
            require("parcel_ref" in contribution, f"contributions[{i}] missing required field: parcel_ref")
            require_type(contribution["parcel_ref"], str, f"contributions[{i}].parcel_ref")
            require(contribution["parcel_ref"] in sharing_refs, f"contributions[{i}].parcel_ref missing matching sharing_settings entry")
        require_number(contribution["delayed_minutes"], f"contributions[{i}].delayed_minutes", minimum=0)
        hazards = contribution["hazards"]
        require_type(hazards, dict, f"contributions[{i}].hazards")
        for field in ("smoke_probability", "flood_probability", "heat_probability"):
            require_number(hazards[field], f"contributions[{i}].hazards.{field}", minimum=0, maximum=1)


def validate_sharing_store(payload):
    required = ["updated_at", "parcels"]
    for field in required:
        require(field in payload, f"sharing store missing required field: {field}")
    require_type(payload["updated_at"], str, "updated_at")
    parcels = payload["parcels"]
    require_type(parcels, list, "parcels")
    require(len(parcels) > 0, "parcels must not be empty")
    refs = set()
    for i, entry in enumerate(parcels):
        require_type(entry, dict, f"parcels[{i}]")
        for field in ("parcel_id", "parcel_ref", "sharing"):
            require(field in entry, f"parcels[{i}] missing required field: {field}")
        require_type(entry["parcel_id"], str, f"parcels[{i}].parcel_id")
        require_type(entry["parcel_ref"], str, f"parcels[{i}].parcel_ref")
        require(entry["parcel_ref"] not in refs, f"parcels[{i}].parcel_ref must be unique")
        refs.add(entry["parcel_ref"])
        validate_sharing_settings(entry["sharing"])


def validate_node_registry(payload):
    required = ["updated_at", "parcel_id", "nodes"]
    for field in required:
        require(field in payload, f"node registry missing required field: {field}")

    require_type(payload["updated_at"], str, "updated_at")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["nodes"], list, "nodes")
    require(len(payload["nodes"]) > 0, "nodes must not be empty")

    valid_node_classes = {
        "indoor_air",
        "outdoor_reference",
        "outdoor_pm_weather",
        "low_point_flood",
        "thermal_scene",
    }
    valid_hardware_families = {
        "bench-air-node",
        "mast-lite",
        "weather-pm-mast",
        "flood-node",
        "thermal-pod",
    }
    valid_location_modes = {"indoor", "sheltered", "outdoor"}
    valid_transport_modes = {"serial_only", "serial_bridge", "https_push", "mqtt"}
    valid_power_modes = {"usb_c_mains", "ac_adapter", "poe", "battery", "solar_assist"}
    valid_calibration_states = {"provisional", "verified", "needs_service", "unsupported"}
    valid_privacy_modes = {"derived_only", "bounded_internal", "full_frame_internal"}

    node_ids = set()
    for i, node in enumerate(payload["nodes"]):
        require_type(node, dict, f"nodes[{i}]")
        for field in (
            "node_id",
            "node_class",
            "hardware_family",
            "schema_version",
            "observation_family",
            "location_mode",
            "install_role",
            "transport_mode",
            "power_mode",
            "calibration_state",
            "installed_at",
            "last_seen_at",
            "enabled",
        ):
            require(field in node, f"nodes[{i}] missing required field: {field}")

        require_type(node["node_id"], str, f"nodes[{i}].node_id")
        require(node["node_id"] not in node_ids, f"nodes[{i}].node_id must be unique")
        node_ids.add(node["node_id"])
        require(node["node_class"] in valid_node_classes, f"nodes[{i}].node_class invalid")
        require(node["hardware_family"] in valid_hardware_families, f"nodes[{i}].hardware_family invalid")
        require_type(node["schema_version"], str, f"nodes[{i}].schema_version")
        require(node["schema_version"].startswith("oesis."), f"nodes[{i}].schema_version invalid")
        require_type(node["observation_family"], str, f"nodes[{i}].observation_family")
        require(node["location_mode"] in valid_location_modes, f"nodes[{i}].location_mode invalid")
        require_type(node["install_role"], str, f"nodes[{i}].install_role")
        require(node["transport_mode"] in valid_transport_modes, f"nodes[{i}].transport_mode invalid")
        require(node["power_mode"] in valid_power_modes, f"nodes[{i}].power_mode invalid")
        require(node["calibration_state"] in valid_calibration_states, f"nodes[{i}].calibration_state invalid")
        require_type(node["installed_at"], str, f"nodes[{i}].installed_at")
        require_type(node["last_seen_at"], str, f"nodes[{i}].last_seen_at")
        require_type(node["enabled"], bool, f"nodes[{i}].enabled")

        if "firmware_version" in node:
            require_type(node["firmware_version"], str, f"nodes[{i}].firmware_version")
        if "privacy_mode" in node:
            require(node["privacy_mode"] in valid_privacy_modes, f"nodes[{i}].privacy_mode invalid")


def validate_operator_access_event(payload):
    required = ["event_id", "occurred_at", "actor", "action", "parcel_id", "data_classes", "justification"]
    for field in required:
        require(field in payload, f"operator access event missing required field: {field}")
    require_type(payload["event_id"], str, "event_id")
    require_type(payload["occurred_at"], str, "occurred_at")
    require_type(payload["actor"], str, "actor")
    require_type(payload["action"], str, "action")
    require_type(payload["parcel_id"], str, "parcel_id")
    require_type(payload["data_classes"], list, "data_classes")
    require(len(payload["data_classes"]) > 0, "data_classes must not be empty")
    valid_classes = {"private_parcel_data", "shared_data", "public_context", "derived_parcel_state", "administrative_record"}
    for i, value in enumerate(payload["data_classes"]):
        require(value in valid_classes, f"data_classes[{i}] invalid")
    require_type(payload["justification"], str, "justification")


def validate_rights_request_store(payload):
    required = ["updated_at", "requests"]
    for field in required:
        require(field in payload, f"rights request store missing required field: {field}")
    require_type(payload["updated_at"], str, "updated_at")
    require_type(payload["requests"], list, "requests")
    for i, request in enumerate(payload["requests"]):
        require_type(request, dict, f"requests[{i}]")
        validate_rights_request(request)


def validate_export_bundle(payload):
    required = ["generated_at", "parcel_id", "sharing", "rights_requests", "access_events", "parcel_state"]
    for field in required:
        require(field in payload, f"export bundle missing required field: {field}")
    require_type(payload["generated_at"], str, "generated_at")
    require_type(payload["parcel_id"], str, "parcel_id")
    require(isinstance(payload["sharing"], (dict, type(None))), "sharing: expected object or null")
    require_type(payload["rights_requests"], list, "rights_requests")
    for i, request in enumerate(payload["rights_requests"]):
        require_type(request, dict, f"rights_requests[{i}]")
        validate_rights_request(request)
    require_type(payload["access_events"], list, "access_events")
    for i, event in enumerate(payload["access_events"]):
        require_type(event, dict, f"access_events[{i}]")
        validate_operator_access_event(event)
    require(isinstance(payload["parcel_state"], (dict, type(None))), "parcel_state: expected object or null")


def validate_retention_cleanup_report(payload):
    required = ["ran_at", "access_events_removed", "rights_requests_removed", "notes"]
    for field in required:
        require(field in payload, f"retention cleanup report missing required field: {field}")
    require_type(payload["ran_at"], str, "ran_at")
    require_number(payload["access_events_removed"], "access_events_removed", minimum=0)
    require_number(payload["rights_requests_removed"], "rights_requests_removed", minimum=0)
    require_type(payload["notes"], list, "notes")
    for i, note in enumerate(payload["notes"]):
        require_type(note, str, f"notes[{i}]")


def validate_normalized_observation(payload):
    required = [
        "observation_id",
        "node_id",
        "parcel_id",
        "observed_at",
        "ingested_at",
        "observation_type",
        "values",
        "health",
        "provenance",
        "raw_packet",
    ]
    for field in required:
        require(field in payload, f"normalized observation missing required field: {field}")

    require_type(payload["observation_id"], str, "observation_id")
    require_type(payload["node_id"], str, "node_id")
    require(isinstance(payload["parcel_id"], (str, type(None))), "parcel_id: expected string or null")
    require_type(payload["observed_at"], str, "observed_at")
    require_type(payload["ingested_at"], str, "ingested_at")
    require(payload["observation_type"] == "air.node.snapshot", "observation_type must be air.node.snapshot")

    values = payload["values"]
    require_type(values, dict, "values")
    for field in ("temperature_c_primary", "relative_humidity_pct_primary", "pressure_hpa", "gas_resistance_ohm"):
        require_number(values[field], f"values.{field}")

    health = payload["health"]
    require_type(health, dict, "health")
    require_number(health["uptime_s"], "health.uptime_s", minimum=0)
    require_type(health["wifi_connected"], bool, "health.wifi_connected")
    require_number(health["read_failures_total"], "health.read_failures_total", minimum=0)

    provenance = payload["provenance"]
    require_type(provenance, dict, "provenance")
    require(provenance["source_kind"] == "homeowner_node", "provenance.source_kind invalid")
    require(provenance["schema_version"] == "oesis.bench-air.v1", "provenance.schema_version invalid")
    require_type(provenance["firmware_version"], str, "provenance.firmware_version")
    require_type(provenance["raw_packet_ref"], str, "provenance.raw_packet_ref")

    validate_node_observation(payload["raw_packet"])


def main():
    files = [
        ("node observation", EXAMPLES_DIR / "node-observation.example.json", validate_node_observation),
        ("normalized observation", EXAMPLES_DIR / "normalized-observation.example.json", validate_normalized_observation),
        ("parcel context", EXAMPLES_DIR / "parcel-context.example.json", validate_parcel_context),
        ("raw public weather", EXAMPLES_DIR / "raw-public-weather.example.json", validate_raw_public_weather),
        ("raw public smoke", EXAMPLES_DIR / "raw-public-smoke.example.json", validate_raw_public_smoke),
        ("public context", EXAMPLES_DIR / "public-context.example.json", validate_public_context),
        ("parcel state", EXAMPLES_DIR / "parcel-state.example.json", validate_parcel_state),
        ("evidence summary", EXAMPLES_DIR / "evidence-summary.example.json", validate_evidence_summary),
        ("sharing settings", EXAMPLES_DIR / "sharing-settings.example.json", validate_sharing_settings),
        ("node registry", EXAMPLES_DIR / "node-registry.example.json", validate_node_registry),
        ("consent record", EXAMPLES_DIR / "consent-record.example.json", validate_consent_record),
        ("rights request", EXAMPLES_DIR / "rights-request.example.json", validate_rights_request),
        ("shared neighborhood signal", EXAMPLES_DIR / "shared-neighborhood-signal.example.json", validate_shared_neighborhood_signal),
        ("sharing store", EXAMPLES_DIR / "sharing-store.example.json", validate_sharing_store),
        ("operator access event", EXAMPLES_DIR / "operator-access-event.example.json", validate_operator_access_event),
        ("rights request store", EXAMPLES_DIR / "rights-request-store.example.json", validate_rights_request_store),
        ("export bundle", EXAMPLES_DIR / "export-bundle.example.json", validate_export_bundle),
        ("retention cleanup report", EXAMPLES_DIR / "retention-cleanup-report.example.json", validate_retention_cleanup_report),
    ]

    failures = []
    for label, path, validator in files:
        try:
            payload = load_json(path)
            validator(payload)
            print(f"PASS {label}: {path}")
        except (ValidationError, KeyError) as exc:
            failures.append(f"FAIL {label}: {path} -> {exc}")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
