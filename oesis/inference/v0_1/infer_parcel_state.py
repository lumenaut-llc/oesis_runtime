#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from oesis.common.repo_paths import EXAMPLES_DIR, INFERENCE_CONFIG_DIR
from oesis.common.runtime_lane import resolve_runtime_lane, versioning_payload
from oesis.inference.parcel_first_hazard import (
    apply_public_and_shared_support,
    build_contrastive_explanations,
    build_divergence_records,
    build_parcel_prior_details,
    build_state_snapshot,
    derive_public_baseline_confidence,
    derive_public_baseline_hazards,
)

CONFIG_DIR = INFERENCE_CONFIG_DIR
PUBLIC_CONTEXT_POLICY_PATH = CONFIG_DIR / "public_context_policy.json"
HAZARD_THRESHOLDS_PATH = CONFIG_DIR / "hazard_thresholds_v0.json"
TRUST_GATES_PATH = CONFIG_DIR / "trust_gates_v0.json"


class InferenceError(Exception):
    pass


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def status_from_probability(probability: float, *, unknown_floor: float = 0.2) -> str:
    if probability < unknown_floor:
        return "unknown"
    if probability < 0.4:
        return "safe"
    if probability < 0.7:
        return "caution"
    return "unsafe"


def parse_time(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def validate_normalized_observation(payload: dict):
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
    ]
    for field in required:
        if field not in payload:
            raise InferenceError(f"normalized observation missing required field: {field}")

    if payload["observation_type"] != "air.node.snapshot":
        raise InferenceError("observation_type must be air.node.snapshot")


def validate_public_context(payload: dict):
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
        if field not in payload:
            raise InferenceError(f"public context missing required field: {field}")

    if payload["source_kind"] != "public_context":
        raise InferenceError("public context source_kind must be public_context")


def validate_parcel_context(payload: dict):
    required = ["parcel_id", "site_profile", "node_installations", "parcel_priors"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"parcel context missing required field: {field}")


def validate_shared_neighborhood_signal(payload: dict):
    required = ["generated_at", "min_participants", "sharing_settings", "contributions"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"shared neighborhood signal missing required field: {field}")


def validate_house_state(payload: dict):
    required = ["parcel_id", "captured_at", "indoor_response", "power_state"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"house state missing required field: {field}")


def validate_house_capability(payload: dict):
    required = ["parcel_id", "effective_at", "capabilities"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"house capability missing required field: {field}")


def validate_equipment_state_observation(payload: dict):
    required = ["parcel_id", "captured_at", "confidence_band", "source", "signals"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"equipment state observation missing required field: {field}")


def validate_source_provenance_record(payload: dict):
    required = ["parcel_id", "captured_at", "records"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"source provenance record missing required field: {field}")


def validate_intervention_event(payload: dict):
    required = ["parcel_id", "event_id", "occurred_at", "action_type", "action_source"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"intervention event missing required field: {field}")


def validate_verification_outcome(payload: dict):
    required = ["parcel_id", "verification_id", "verified_at", "hazard_type", "result_class"]
    for field in required:
        if field not in payload:
            raise InferenceError(f"verification outcome missing required field: {field}")


@lru_cache(maxsize=1)
def _public_context_policy() -> dict:
    return load_json(PUBLIC_CONTEXT_POLICY_PATH)


@lru_cache(maxsize=1)
def _hazard_thresholds() -> dict:
    return load_json(HAZARD_THRESHOLDS_PATH)


@lru_cache(maxsize=1)
def _trust_gates() -> dict:
    return load_json(TRUST_GATES_PATH)


def get_policy_for_source(source_name: str) -> dict:
    policy = _public_context_policy()
    default_policy = policy["default_policy"]
    override = policy.get("source_overrides", {}).get(source_name, {})
    return {
        "fresh_max_age_seconds": override.get("fresh_max_age_seconds", default_policy["fresh_max_age_seconds"]),
        "aging_max_age_seconds": override.get("aging_max_age_seconds", default_policy["aging_max_age_seconds"]),
        "stale_max_age_seconds": override.get("stale_max_age_seconds", default_policy["stale_max_age_seconds"]),
        "hazard_multiplier": default_policy["hazard_multiplier"],
        "confidence_adjustment": default_policy["confidence_adjustment"],
    }


def probability_from_lt_bands(value: float | None, bands: list[dict], default_probability: float) -> float:
    if value is None:
        return default_probability
    for band in bands:
        if value < band["lt"]:
            return band["probability"]
    return default_probability


def probability_from_gte_bands(value: float | None, bands: list[dict], default_probability: float) -> float:
    if value is None:
        return default_probability
    for band in bands:
        if value >= band["gte"]:
            return band["probability"]
    return default_probability


def build_closed_loop_summary(
    *,
    house_state: dict | None,
    intervention_event: dict | None,
    verification_outcome: dict | None,
    smoke_config: dict,
) -> dict:
    summary = {
        "hazard_type": "smoke",
        "status": "not_attempted",
        "summary": "No smoke-response loop has been attempted yet.",
    }

    if house_state and house_state.get("indoor_response"):
        indoor_response = house_state["indoor_response"]
        summary["current_indoor_response"] = {
            "pm25_ugm3": indoor_response.get("pm25_ugm3"),
            "temperature_c": indoor_response.get("temperature_c"),
            "relative_humidity_pct": indoor_response.get("relative_humidity_pct"),
        }

    smoke_intervention = intervention_event and intervention_event.get("action_type") in {
        "hvac_recirculate_on",
        "purifier_started",
        "fan_continuous_on",
    }

    if smoke_intervention:
        summary["status"] = "awaiting_verification"
        summary["action_type"] = intervention_event.get("action_type")
        summary["action_source"] = intervention_event.get("action_source")
        summary["summary"] = (
            f"Smoke-response action `{intervention_event.get('action_type')}` was recorded; "
            "verification is still pending or incomplete."
        )

    if verification_outcome and verification_outcome.get("hazard_type") == "smoke":
        window = verification_outcome.get("response_window_minutes")
        before = verification_outcome.get("before", {})
        after = verification_outcome.get("after", {})
        before_pm = before.get("indoor_pm25_ugm3")
        after_pm = after.get("indoor_pm25_ugm3")
        delta = None
        ratio = None
        if isinstance(before_pm, (int, float)) and isinstance(after_pm, (int, float)):
            delta = round(before_pm - after_pm, 2)
            ratio = round((before_pm - after_pm) / before_pm, 2) if before_pm > 0 else None

        window_ok = (
            isinstance(window, int)
            and smoke_config["verification_window_min_minutes"] <= window <= smoke_config["verification_window_max_minutes"]
        )
        improved = (
            verification_outcome.get("result_class") == "improved"
            and window_ok
            and delta is not None
            and ratio is not None
            and delta >= smoke_config["improvement_absolute_min_ugm3"]
            and ratio >= smoke_config["improvement_ratio_min"]
        )

        summary.update(
            {
                "response_window_minutes": window,
                "before": before,
                "after": after,
                "improvement_delta": delta,
                "improvement_ratio": ratio,
                "intervention_ref": verification_outcome.get("intervention_ref"),
            }
        )

        if improved:
            summary["status"] = "verified_improved"
            summary["summary"] = (
                f"Smoke-response loop verified improvement over {window} minutes"
                + (
                    f" after `{intervention_event.get('action_type')}`."
                    if smoke_intervention
                    else "."
                )
            )
        elif verification_outcome.get("result_class") == "worsened":
            summary["status"] = "verified_not_improved"
            summary["summary"] = "Smoke-response verification showed worsening conditions over the measured window."
        elif verification_outcome.get("result_class") == "unchanged":
            summary["status"] = "verified_not_improved"
            summary["summary"] = "Smoke-response verification did not show a meaningful indoor improvement over the measured window."
        else:
            summary["status"] = "inconclusive"
            summary["summary"] = "Smoke-response verification is present but remains inconclusive."

    return summary


def public_context_age_seconds(public_context: dict, *, now: datetime) -> int:
    return max(0, int((now - parse_time(public_context["observed_at"])).total_seconds()))


def public_context_freshness_band(public_context: dict, *, now: datetime) -> str:
    policy = get_policy_for_source(public_context["source_name"])
    age_seconds = public_context_age_seconds(public_context, now=now)
    if age_seconds <= policy["fresh_max_age_seconds"]:
        return "fresh"
    if age_seconds <= policy["aging_max_age_seconds"]:
        return "aging"
    if age_seconds <= policy["stale_max_age_seconds"]:
        return "stale"
    return "expired"


def combine_public_contexts(public_contexts: list[dict]) -> dict | None:
    if not public_contexts:
        return None

    for context in public_contexts:
        validate_public_context(context)

    first = public_contexts[0]
    combined_summary = []
    combined_source_names = []
    combined_hazards = {
        "smoke_probability": 0.0,
        "heat_probability": 0.0,
        "flood_probability": 0.0,
    }
    combined_observed_at = first["observed_at"]
    members = []

    for context in public_contexts:
        if context["parcel_id"] != first["parcel_id"]:
            raise InferenceError("public contexts must share the same parcel_id")
        if context["coverage_mode"] != first["coverage_mode"]:
            raise InferenceError("public contexts must share the same coverage_mode")
        combined_source_names.append(context["source_name"])
        combined_summary.extend(context.get("summary", []))
        for hazard_name in combined_hazards:
            combined_hazards[hazard_name] = max(
                combined_hazards[hazard_name],
                context["hazards"][hazard_name],
            )
        if parse_time(context["observed_at"]) > parse_time(combined_observed_at):
            combined_observed_at = context["observed_at"]
        members.append(
            {
                "source_name": context["source_name"],
                "observed_at": context["observed_at"],
                "hazards": context["hazards"],
                "summary": context.get("summary", []),
                "raw_context": context.get("raw_context"),
            }
        )

    return {
        "context_id": "combined_public_context",
        "source_kind": "public_context",
        "source_name": ",".join(combined_source_names),
        "observed_at": combined_observed_at,
        "coverage_mode": first["coverage_mode"],
        "parcel_id": first["parcel_id"],
        "hazards": combined_hazards,
        "summary": combined_summary,
        "members": members,
    }


def build_shared_neighborhood_context(shared_signal: dict) -> dict | None:
    validate_shared_neighborhood_signal(shared_signal)

    allowed_parcels = {
        item["parcel_ref"]
        for item in shared_signal.get("sharing_settings", [])
        if item.get("neighborhood_aggregate") and not item.get("revocation_pending")
    }

    eligible = []
    for contribution in shared_signal.get("contributions", []):
        if contribution.get("source_class") != "shared_data":
            continue
        parcel_ref = contribution.get("parcel_ref")
        if parcel_ref not in allowed_parcels:
            continue
        eligible.append(contribution)

    if len(eligible) < shared_signal["min_participants"]:
        return None

    cell_counts = {}
    for contribution in eligible:
        cell_id = contribution["cell_id"]
        cell_counts[cell_id] = cell_counts.get(cell_id, 0) + 1

    best_cell_id = None
    best_count = 0
    for cell_id, count in cell_counts.items():
        if count > best_count:
            best_cell_id = cell_id
            best_count = count

    if best_cell_id is None or best_count < shared_signal["min_participants"]:
        return None

    cell_contributions = [item for item in eligible if item["cell_id"] == best_cell_id]
    hazard_keys = ("smoke_probability", "flood_probability", "heat_probability")
    hazards = {}
    for hazard_key in hazard_keys:
        hazards[hazard_key] = round(
            sum(item["hazards"][hazard_key] for item in cell_contributions) / len(cell_contributions),
            2,
        )

    max_delay = max(item.get("delayed_minutes", 0) for item in cell_contributions)
    summary = [
        f"Shared neighborhood signal from {len(cell_contributions)} contributing parcels in {best_cell_id} suggests nearby conditions worth watching."
    ]
    if hazards["smoke_probability"] >= 0.3:
        summary.append("Nearby shared signals suggest modest smoke concern in the surrounding cell.")
    elif hazards["heat_probability"] >= 0.3:
        summary.append("Nearby shared signals suggest modest heat concern in the surrounding cell.")

    return {
        "context_id": "shared_neighborhood_context",
        "source_kind": "shared_data",
        "source_name": "shared_neighborhood_signal",
        "observed_at": shared_signal["generated_at"],
        "coverage_mode": "cell",
        "parcel_id": None,
        "hazards": hazards,
        "summary": summary,
        "member_count": len(cell_contributions),
        "max_delay_minutes": max_delay,
        "cell_id": best_cell_id,
    }


def get_location_mode(payload: dict) -> str:
    raw_packet = payload.get("raw_packet", {})
    return raw_packet.get("location_mode", "indoor")


def find_node_installation(parcel_context: dict | None, node_id: str) -> dict | None:
    if not parcel_context:
        return None
    for installation in parcel_context.get("node_installations", []):
        if installation.get("node_id") == node_id:
            return installation
    return None


def classify_local_context(payload: dict, parcel_context: dict | None = None) -> dict:
    installation = find_node_installation(parcel_context, payload["node_id"])
    location_mode = installation.get("location_mode", get_location_mode(payload)) if installation else get_location_mode(payload)
    is_indoor = location_mode == "indoor"
    is_sheltered = location_mode == "sheltered"
    is_outdoor = location_mode == "outdoor"
    local_observability = "low"
    if is_outdoor:
        local_observability = "moderate"
    elif is_sheltered:
        local_observability = "limited"

    return {
        "location_mode": location_mode,
        "is_indoor": is_indoor,
        "is_sheltered": is_sheltered,
        "is_outdoor": is_outdoor,
        "local_observability": local_observability,
        "install_role": installation.get("install_role", "unknown") if installation else "unknown",
        "exposure_bias_flags": installation.get("exposure_bias_flags", []) if installation else [],
        "has_parcel_context": parcel_context is not None,
    }


def prior_adjustment(prior_value: str | None, *, low: float = -0.02, moderate: float = 0.0, high: float = 0.04) -> float:
    mapping = {
        "low": low,
        "moderate": moderate,
        "high": high,
        "unknown": 0.0,
        None: 0.0,
    }
    return mapping.get(prior_value, 0.0)


def derive_hazards(
    payload: dict,
    parcel_context: dict | None = None,
    house_state: dict | None = None,
    house_capability: dict | None = None,
    verification_outcome: dict | None = None,
    shared_neighborhood_context: dict | None = None,
    public_context: dict | None = None,
    *,
    now: datetime,
) -> dict:
    values = payload["values"]
    health = payload["health"]
    context = classify_local_context(payload, parcel_context=parcel_context)
    smoke_config = _hazard_thresholds()["smoke"]
    heat_config = _hazard_thresholds()["heat"]
    sensor_penalties = _hazard_thresholds()["sensor_penalties"]
    parcel_prior_details = build_parcel_prior_details(parcel_context)

    smoke_probability = smoke_config["base_probability"]
    gas_resistance = values.get("gas_resistance_ohm")
    smoke_probability = probability_from_lt_bands(
        gas_resistance,
        smoke_config["gas_resistance_bands"],
        smoke_config["default_probability"],
    )

    indoor_response = house_state.get("indoor_response", {}) if house_state else {}
    indoor_pm25 = indoor_response.get("pm25_ugm3")
    indoor_smoke_probability = probability_from_gte_bands(
        indoor_pm25,
        smoke_config["indoor_pm25_bands"],
        smoke_probability,
    )
    smoke_probability = max(smoke_probability, indoor_smoke_probability)

    heat_probability = heat_config["base_probability"]
    temperature_c = values.get("temperature_c_primary")
    heat_probability = probability_from_gte_bands(
        temperature_c,
        heat_config["temperature_bands"],
        heat_config["base_probability"],
    )

    if context["is_indoor"]:
        heat_probability -= heat_config["indoor_penalty"]
    elif context["is_sheltered"]:
        heat_probability -= heat_config["sheltered_penalty"]

    heat_probability += parcel_prior_details["heat"]["adjustment"]
    smoke_probability += parcel_prior_details["smoke"]["adjustment"]

    if house_capability:
        capabilities = house_capability.get("capabilities", {})
        if capabilities.get("recirculation_available"):
            smoke_probability += 0.01

    if verification_outcome and verification_outcome.get("hazard_type") == "smoke":
        if verification_outcome.get("result_class") == "worsened":
            smoke_probability += 0.03

    flood_probability = 0.0

    if not health.get("wifi_connected", False):
        smoke_probability -= sensor_penalties["wifi_disconnected"]
        heat_probability -= sensor_penalties["wifi_disconnected"]

    if health.get("read_failures_total", 0) > 0:
        smoke_probability -= sensor_penalties["read_failures"]
        heat_probability -= sensor_penalties["read_failures"]

    flood_probability = max(flood_probability, parcel_prior_details["flood"]["probability"])

    return apply_public_and_shared_support(
        {
            "smoke_probability": smoke_probability,
            "flood_probability": flood_probability,
            "heat_probability": heat_probability,
        },
        public_context=public_context,
        shared_context=shared_neighborhood_context,
        now=now,
        public_context_freshness_band=public_context_freshness_band,
        get_policy_for_source=get_policy_for_source,
    )


def derive_confidence(
    payload: dict,
    hazards: dict,
    *,
    now: datetime,
    parcel_context: dict | None = None,
    house_state: dict | None = None,
    house_capability: dict | None = None,
    intervention_event: dict | None = None,
    verification_outcome: dict | None = None,
    shared_neighborhood_context: dict | None = None,
    public_context: dict | None = None,
) -> float:
    observed_at = parse_time(payload["observed_at"])
    age_seconds = max(0, int((now - observed_at).total_seconds()))
    context = classify_local_context(payload, parcel_context=parcel_context)

    confidence = 0.52
    if payload["health"].get("read_failures_total", 0) > 0:
        confidence -= 0.1
    if not payload["health"].get("wifi_connected", False):
        confidence -= 0.04
    if context["is_indoor"]:
        confidence -= 0.14
    elif context["is_sheltered"]:
        confidence -= 0.08
    if not context["has_parcel_context"]:
        confidence -= 0.08
    if "hvac_possible" in context["exposure_bias_flags"]:
        confidence -= 0.04
    if age_seconds > 900:
        confidence -= 0.1
    if age_seconds > 3600:
        confidence -= 0.15

    if max(hazards.values()) < 0.2:
        confidence -= 0.08
    if house_state is not None:
        confidence += 0.08
    if house_capability is not None:
        confidence += 0.04
    if intervention_event is not None:
        confidence += 0.02
    if verification_outcome is not None and verification_outcome.get("result_class") != "inconclusive":
        confidence += 0.03
    if public_context:
        member_contexts = public_context.get("members", [public_context])
        confidence_adjustment = min(
            0.18,
            sum(
                get_policy_for_source(member["source_name"])["confidence_adjustment"][
                    public_context_freshness_band(member, now=now)
                ]
                for member in member_contexts
            ),
        )
        confidence += confidence_adjustment
    if shared_neighborhood_context:
        confidence += 0.06

    return clamp_probability(confidence)


def derive_reasons(
    payload: dict,
    confidence: float,
    evidence_contributions: list[dict],
    *,
    parcel_context: dict | None = None,
    public_context: dict | None = None,
    parcel_prior_details: dict | None = None,
    contrastive_explanations: list[dict] | None = None,
) -> list[str]:
    reasons = []
    context = classify_local_context(payload, parcel_context=parcel_context)
    parcel_priors = parcel_context.get("parcel_priors", {}) if parcel_context else {}

    for contribution in evidence_contributions[:6]:
        reasons.append(contribution["summary"])

    if parcel_prior_details:
        for hazard_name in ("heat", "smoke", "flood"):
            summary = parcel_prior_details[hazard_name]["summary"]
            if summary:
                reasons.append(summary)
    elif parcel_priors.get("heat_retention_class") == "high":
        reasons.append("Parcel prior suggests elevated heat retention, which modestly raises heat support.")
    elif parcel_priors.get("heat_retention_class") == "low":
        reasons.append("Parcel prior suggests lower heat retention, which modestly reduces heat support.")

    if context["is_indoor"]:
        reasons.append("Current local evidence comes from an indoor node and does not directly represent parcel-wide outdoor conditions.")
    elif context["is_sheltered"]:
        reasons.append("Current local evidence comes from a sheltered node and only partially represents wider parcel conditions.")
    else:
        reasons.append("Current local evidence comes from one outdoor-capable node and still reflects only part of the parcel.")

    if confidence >= 0.5 and public_context:
        reasons.append("Confidence improves because public context supports the local evidence, but parcel certainty is still limited.")
    elif confidence >= 0.5:
        reasons.append("The current decision is based on a single dwelling-associated node without confirming public context.")

    if contrastive_explanations:
        reasons.append(contrastive_explanations[0]["contrast"]["summary"])

    deduped = []
    seen = set()
    for reason in reasons:
        if reason not in seen:
            deduped.append(reason)
            seen.add(reason)

    if not deduped:
        deduped.append("Available evidence is limited, so the parcel state remains mostly unknown.")

    return deduped


def make_evidence_contribution(
    *,
    contribution_id: str,
    source_class: str,
    source_name: str,
    role: str,
    summary: str,
    hazards: list[str],
    weight: float,
    visibility: str = "dwelling_safe",
    freshness_band: str | None = None,
) -> dict:
    contribution = {
        "contribution_id": contribution_id,
        "source_class": source_class,
        "source_name": source_name,
        "role": role,
        "summary": summary,
        "hazards": hazards,
        "weight": round(weight, 2),
        "visibility": visibility,
    }
    if freshness_band is not None:
        contribution["freshness_band"] = freshness_band
    return contribution


def build_evidence_contributions(
    *,
    payload: dict,
    parcel_context: dict | None,
    parcel_prior_details: dict,
    house_state: dict | None,
    house_capability: dict | None,
    equipment_state_observation: dict | None,
    source_provenance_record: dict | None,
    intervention_event: dict | None,
    verification_outcome: dict | None,
    shared_context: dict | None,
    public_context: dict | None,
    divergence_records: list[dict],
    hazards: dict,
    confidence: float,
    stale: bool,
    now: datetime,
) -> list[dict]:
    contributions = []
    context = classify_local_context(payload, parcel_context=parcel_context)

    gas_resistance = payload["values"].get("gas_resistance_ohm")
    if gas_resistance is not None:
        if gas_resistance < 100000:
            summary = "Local gas-resistance trend suggests an indoor or sheltered air anomaly worth checking."
            weight = 0.48
        elif gas_resistance < 180000:
            summary = "Local gas-resistance trend shows a moderate change, but it is not a direct smoke concentration measurement."
            weight = 0.32
        else:
            summary = "Local gas-resistance trend appears comparatively steady."
            weight = 0.12
        contributions.append(
            make_evidence_contribution(
                contribution_id="local_gas_trend",
                source_class="local",
                source_name=payload["node_id"],
                role="driver",
                summary=summary,
                hazards=["smoke"],
                weight=weight,
            )
        )

    temperature_c = payload["values"].get("temperature_c_primary")
    if temperature_c is not None:
        if temperature_c >= 34:
            summary = (
                "Indoor temperature is elevated at the node location, which may indicate local heat burden."
                if context["is_indoor"]
                else "Measured temperature is elevated at the node location and may contribute to heat concern."
            )
            weight = 0.52
        elif temperature_c >= 24:
            summary = (
                "Indoor temperature is somewhat elevated at the node location."
                if context["is_indoor"]
                else "Measured temperature is modestly elevated at the node location."
            )
            weight = 0.28
        else:
            summary = "Local temperature does not currently suggest elevated heat concern."
            weight = 0.1
        contributions.append(
            make_evidence_contribution(
                contribution_id="local_temperature",
                source_class="local",
                source_name=payload["node_id"],
                role="driver",
                summary=summary,
                hazards=["heat"],
                weight=weight,
            )
        )

    siting_summary = "Current local evidence comes from one outdoor-capable node and still reflects only part of the parcel."
    siting_weight = 0.28
    if context["is_indoor"]:
        siting_summary = "Current local evidence comes from an indoor node and does not directly represent parcel-wide outdoor conditions."
        siting_weight = 0.72
    elif context["is_sheltered"]:
        siting_summary = "Current local evidence comes from a sheltered node and only partially represents wider parcel conditions."
        siting_weight = 0.56
    contributions.append(
        make_evidence_contribution(
            contribution_id="local_siting_limit",
            source_class="local",
            source_name=payload["node_id"],
            role="limitation",
            summary=siting_summary,
            hazards=["smoke", "heat", "flood"],
            weight=siting_weight,
        )
    )

    if parcel_context:
        installation = find_node_installation(parcel_context, payload["node_id"])
        if installation:
            contributions.append(
                make_evidence_contribution(
                    contribution_id="parcel_install_role",
                    source_class="parcel_context",
                    source_name=installation.get("install_role", "unknown"),
                    role="limitation",
                    summary=(
                        f"Install role {installation.get('install_role', 'unknown')} constrains how strongly this node "
                        "represents wider parcel conditions."
                    ),
                    hazards=["smoke", "heat", "flood"],
                    weight=0.44,
                )
            )
        else:
            contributions.append(
                make_evidence_contribution(
                    contribution_id="parcel_missing_installation",
                    source_class="parcel_context",
                    source_name=parcel_context["parcel_id"],
                    role="limitation",
                    summary="Parcel context is present, but this node lacks a matching installation record.",
                    hazards=["smoke", "heat", "flood"],
                    weight=0.46,
                )
            )
    else:
        contributions.append(
            make_evidence_contribution(
                contribution_id="missing_parcel_context",
                source_class="system",
                source_name=payload["parcel_id"],
                role="limitation",
                summary="Parcel installation context is missing, so siting relevance and parcel priors cannot improve interpretation.",
                hazards=["smoke", "heat", "flood"],
                weight=0.64,
            )
        )

    if parcel_context:
        if parcel_prior_details["heat"]["factors"]:
            contributions.append(
                make_evidence_contribution(
                    contribution_id="parcel_heat_prior",
                    source_class="parcel_context",
                    source_name=parcel_context["parcel_id"],
                    role="driver",
                    summary=parcel_prior_details["heat"]["summary"],
                    hazards=["heat"],
                    weight=min(0.3, abs(parcel_prior_details["heat"]["adjustment"]) + 0.08),
                )
            )
        if parcel_prior_details["smoke"]["factors"]:
            contributions.append(
                make_evidence_contribution(
                    contribution_id="parcel_smoke_prior",
                    source_class="parcel_context",
                    source_name=parcel_context["parcel_id"],
                    role="driver",
                    summary=parcel_prior_details["smoke"]["summary"],
                    hazards=["smoke"],
                    weight=min(0.34, abs(parcel_prior_details["smoke"]["adjustment"]) + 0.12),
                )
            )
        contributions.append(
            make_evidence_contribution(
                contribution_id="parcel_flood_prior",
                source_class="parcel_context",
                source_name=parcel_context["parcel_id"],
                role="driver",
                summary=parcel_prior_details["flood"]["summary"],
                hazards=["flood"],
                weight=min(0.38, parcel_prior_details["flood"]["probability"] * 8 + 0.08),
            )
        )

    for record in divergence_records:
        hazard = {
            "pm25": "smoke",
            "temperature_c": "heat",
            "flood_stage": "flood",
        }.get(record["parameter"], "smoke")
        role = "driver" if record["magnitude"] in {"moderate", "high", "extreme"} else "limitation"
        summary = (
            f"Local {record['parameter']} diverged from {record['regional_source']} by {record['abs_diff']:.1f} "
            f"({record['direction']}, {record['persistence_class']})."
        )
        contributions.append(
            make_evidence_contribution(
                contribution_id=f"divergence_{record['parameter']}",
                source_class="system",
                source_name=record["regional_source"],
                role=role,
                summary=summary,
                hazards=[hazard],
                weight=min(0.62, (record["z_score"] or 0.0) * 0.12 + 0.12),
            )
        )

    if house_state:
        indoor_response = house_state.get("indoor_response", {})
        indoor_pm25 = indoor_response.get("pm25_ugm3")
        indoor_temp = indoor_response.get("temperature_c")
        if indoor_pm25 is not None:
            contributions.append(
                make_evidence_contribution(
                    contribution_id="indoor_pm25_support",
                    source_class="local",
                    source_name=house_state.get("source_summary", {}).get("source_kind", "private_support_object"),
                    role="driver",
                    summary=f"Indoor PM2.5 support data is available ({round(indoor_pm25, 1)} ug/m3).",
                    hazards=["smoke"],
                    weight=0.26 if indoor_pm25 >= 12 else 0.14,
                )
            )
        if indoor_temp is not None:
            contributions.append(
                make_evidence_contribution(
                    contribution_id="indoor_temperature_support",
                    source_class="local",
                    source_name=house_state.get("source_summary", {}).get("source_kind", "private_support_object"),
                    role="driver",
                    summary=f"Indoor response temperature support is available ({round(indoor_temp, 1)} C).",
                    hazards=["heat"],
                    weight=0.14,
                )
            )
        power_state = house_state.get("power_state", {})
        if power_state:
            mains_state = power_state.get("mains_state", "unknown")
            backup_active = power_state.get("backup_power_active")
            contributions.append(
                make_evidence_contribution(
                    contribution_id="power_state_support",
                    source_class="local",
                    source_name=house_state.get("source_summary", {}).get("source_kind", "private_support_object"),
                    role="driver" if mains_state == "down" else "limitation",
                    summary=(
                        "Household continuity data shows mains power is down."
                        if mains_state == "down"
                        else "Household continuity data is available for mains and backup-power posture."
                    ),
                    hazards=["heat", "flood"],
                    weight=0.22 if mains_state == "down" and not backup_active else 0.12,
                )
            )

    if house_capability:
        capabilities = house_capability.get("capabilities", {})
        equipment_state = house_capability.get("equipment_state", {})
        if capabilities.get("recirculation_available") or capabilities.get("portable_purifier_present"):
            contributions.append(
                make_evidence_contribution(
                    contribution_id="protective_capability_present",
                    source_class="parcel_context",
                    source_name=payload["parcel_id"],
                    role="driver",
                    summary="Protective capability metadata indicates recirculation and/or purifier support is available.",
                    hazards=["smoke"],
                    weight=0.18,
                )
            )
        if equipment_state:
            state_parts = []
            if equipment_state.get("air_source_mode"):
                state_parts.append(f"air mode={equipment_state['air_source_mode']}")
            if equipment_state.get("fan_state"):
                state_parts.append(f"fan={equipment_state['fan_state']}")
            if equipment_state.get("purifier_state"):
                state_parts.append(f"purifier={equipment_state['purifier_state']}")
            if state_parts:
                contributions.append(
                    make_evidence_contribution(
                        contribution_id="equipment_state_support",
                        source_class="parcel_context",
                        source_name=payload["parcel_id"],
                        role="driver",
                        summary=f"Read-side equipment state is available ({', '.join(state_parts)}).",
                        hazards=["smoke", "heat"],
                        weight=0.2,
                    )
                )

    if equipment_state_observation:
        signals = equipment_state_observation.get("signals", {})
        signal_parts = []
        for field_name in ("hvac_mode", "fan_state", "air_source_mode", "purifier_state", "sump_state"):
            value = signals.get(field_name)
            if value is not None:
                signal_parts.append(f"{field_name}={value}")
        if signal_parts:
            equipment_confidence = equipment_state_observation.get("confidence_band", "unknown")
            contributions.append(
                make_evidence_contribution(
                    contribution_id="equipment_state_observation_support",
                    source_class="local",
                    source_name=equipment_state_observation.get("source", {}).get("source_name", "equipment_state_observation"),
                    role="driver",
                    summary=(
                        f"Adapter/read-side equipment-state observation is available ({', '.join(signal_parts)}; "
                        f"confidence={equipment_confidence})."
                    ),
                    hazards=["smoke", "heat", "flood"],
                    weight=0.17,
                )
            )

    if source_provenance_record:
        records = source_provenance_record.get("records", [])
        if records:
            high_confidence_count = sum(1 for item in records if item.get("confidence_band") == "high")
            stale_count = sum(1 for item in records if item.get("stale") is True)
            contributions.append(
                make_evidence_contribution(
                    contribution_id="source_provenance_support",
                    source_class="system",
                    source_name="source_provenance_record",
                    role="driver" if high_confidence_count > 0 else "limitation",
                    summary=(
                        f"Signal provenance metadata is available for {len(records)} fields "
                        f"({high_confidence_count} high-confidence, {stale_count} stale)."
                    ),
                    hazards=["smoke", "heat", "flood"],
                    weight=0.12 if high_confidence_count > 0 else 0.08,
                )
            )

    if intervention_event:
        contributions.append(
            make_evidence_contribution(
                contribution_id="intervention_history_present",
                source_class="system",
                source_name=intervention_event.get("event_id", "intervention_event"),
                role="driver",
                summary=f"An intervention record is present ({intervention_event.get('action_type', 'unknown_action')}).",
                hazards=["smoke", "heat", "flood"],
                weight=0.16,
            )
        )

    if verification_outcome:
        result_class = verification_outcome.get("result_class", "inconclusive")
        contributions.append(
            make_evidence_contribution(
                contribution_id="verification_history_present",
                source_class="system",
                source_name=verification_outcome.get("verification_id", "verification_outcome"),
                role="driver" if result_class == "improved" else "limitation",
                summary=(
                    "A prior verification record suggests conditions improved after an intervention."
                    if result_class == "improved"
                    else "A verification record is present but does not yet show clear improvement."
                ),
                hazards=[verification_outcome.get("hazard_type", "smoke")],
                weight=0.18 if result_class == "improved" else 0.14,
            )
        )

    if house_state:
        contributions.append(
            make_evidence_contribution(
                contribution_id="house_state_support",
                source_class="local",
                source_name=house_state.get("source_summary", {}).get("source_kind", "private_support_object"),
                role="driver",
                summary="Private house-state support data is available for indoor response and continuity reasoning.",
                hazards=["smoke", "heat", "flood"],
                weight=0.1,
            )
        )

    if house_capability:
        contributions.append(
            make_evidence_contribution(
                contribution_id="house_capability_support",
                source_class="parcel_context",
                source_name=payload["parcel_id"],
                role="driver",
                summary="Protective capability and equipment-state metadata are available for later response reasoning.",
                hazards=["smoke", "heat", "flood"],
                weight=0.08,
            )
        )

    if intervention_event:
        contributions.append(
            make_evidence_contribution(
                contribution_id="intervention_history_present",
                source_class="system",
                source_name=intervention_event.get("event_id", "intervention_event"),
                role="limitation",
                summary="Intervention records are present, but current parcel-state remains a condition estimate rather than a response score.",
                hazards=["smoke", "heat", "flood"],
                weight=0.08,
            )
        )

    if verification_outcome:
        contributions.append(
            make_evidence_contribution(
                contribution_id="verification_history_present",
                source_class="system",
                source_name=verification_outcome.get("verification_id", "verification_outcome"),
                role="limitation",
                summary="Verification records are available for later closed-loop reasoning, but they do not directly change the current parcel-state.",
                hazards=["smoke", "heat", "flood"],
                weight=0.08,
            )
        )

    if public_context:
        for member in public_context.get("members", [public_context]):
            member_hazards = []
            if member["hazards"]["smoke_probability"] >= 0.1:
                member_hazards.append("smoke")
            if member["hazards"]["heat_probability"] >= 0.1:
                member_hazards.append("heat")
            if member["hazards"]["flood_probability"] >= 0.03:
                member_hazards.append("flood")
            if member_hazards:
                freshness_band = public_context_freshness_band(member, now=now)
                contributions.append(
                    make_evidence_contribution(
                        contribution_id=f"public_{member['source_name']}",
                        source_class="public",
                        source_name=member["source_name"],
                        role="driver",
                        summary=member.get("summary", ["Public context contributed to the estimate."])[0],
                        hazards=member_hazards,
                        weight={
                            "fresh": 0.48,
                            "aging": 0.32,
                            "stale": 0.18,
                            "expired": 0.0,
                        }[freshness_band],
                        freshness_band=freshness_band,
                    )
                )
                if freshness_band in {"aging", "stale", "expired"}:
                    contributions.append(
                        make_evidence_contribution(
                            contribution_id=f"public_{member['source_name']}_freshness_limit",
                            source_class="public",
                            source_name=member["source_name"],
                            role="limitation",
                            summary={
                                "aging": "Some regional public context is aging, so it provides limited support.",
                                "stale": "Some regional public context is stale and contributes little weight to the current parcel estimate.",
                                "expired": "Some available public context was too old to materially affect the current parcel estimate.",
                            }[freshness_band],
                            hazards=member_hazards,
                            weight={
                                "aging": 0.28,
                                "stale": 0.46,
                                "expired": 0.7,
                            }[freshness_band],
                            freshness_band=freshness_band,
                        )
                    )

    if shared_context:
        shared_hazards = []
        if shared_context["hazards"]["smoke_probability"] >= 0.2:
            shared_hazards.append("smoke")
        if shared_context["hazards"]["heat_probability"] >= 0.2:
            shared_hazards.append("heat")
        if shared_context["hazards"]["flood_probability"] >= 0.05:
            shared_hazards.append("flood")
        contributions.append(
            make_evidence_contribution(
                contribution_id="shared_cell_signal",
                source_class="shared",
                source_name=shared_context["cell_id"],
                role="driver",
                summary=shared_context["summary"][0],
                hazards=shared_hazards or ["smoke"],
                weight=0.34,
            )
        )
        contributions.append(
            make_evidence_contribution(
                contribution_id="shared_scope_limit",
                source_class="shared",
                source_name=shared_context["cell_id"],
                role="limitation",
                summary="Shared neighborhood signals are nearby supporting context, not direct confirmation of this parcel's conditions.",
                hazards=["smoke", "heat", "flood"],
                weight=0.42,
            )
        )

    if hazards["flood_probability"] == 0:
        contributions.append(
            make_evidence_contribution(
                contribution_id="missing_flood_evidence",
                source_class="parcel_context" if parcel_context else "local",
                source_name=payload["node_id"] if not parcel_context else parcel_context["parcel_id"],
                role="limitation",
                summary="No flood-capable local sensor or public flood context is present.",
                hazards=["flood"],
                weight=0.58,
            )
        )

    if stale:
        contributions.append(
            make_evidence_contribution(
                contribution_id="stale_local_observation",
                source_class="system",
                source_name="freshness_gate",
                role="limitation",
                summary="The latest local observation is aging out and may no longer reflect current parcel conditions.",
                hazards=["smoke", "heat", "flood"],
                weight=_trust_gates()["freshness_gate"]["stale_weight"],
            )
        )

    if confidence < _trust_gates()["confidence_gate"]["low_confidence_threshold"]:
        contributions.append(
            make_evidence_contribution(
                contribution_id="low_confidence_gate",
                source_class="system",
                source_name="confidence_gate",
                role="limitation",
                summary="Confidence is limited because the current estimate relies on sparse or weakly representative evidence.",
                hazards=["smoke", "heat", "flood"],
                weight=_trust_gates()["confidence_gate"]["weight"],
            )
        )

    public_members = public_context.get("members", [public_context]) if public_context else []
    strongest_public_smoke = max((member["hazards"]["smoke_probability"] for member in public_members), default=0.0)
    strongest_public_heat = max((member["hazards"]["heat_probability"] for member in public_members), default=0.0)
    strongest_shared_smoke = shared_context["hazards"]["smoke_probability"] if shared_context else 0.0
    strongest_shared_heat = shared_context["hazards"]["heat_probability"] if shared_context else 0.0

    disagreement = _trust_gates()["cross_source_disagreement"]

    if (
        gas_resistance is not None
        and gas_resistance >= disagreement["smoke_local_steady_min_gas_resistance_ohm"]
        and max(strongest_public_smoke, strongest_shared_smoke) >= disagreement["smoke_external_support_threshold"]
    ):
        contributions.append(
            make_evidence_contribution(
                contribution_id="smoke_disagreement_gate",
                source_class="system",
                source_name="cross_source_agreement",
                role="limitation",
                summary="Regional or neighborhood smoke context is stronger than the local node trend, so the estimate remains conservative.",
                hazards=["smoke"],
                weight=disagreement["weight"],
            )
        )

    if (
        temperature_c is not None
        and temperature_c < disagreement["heat_local_cool_max_temp_c"]
        and max(strongest_public_heat, strongest_shared_heat) >= disagreement["heat_external_support_threshold"]
    ):
        contributions.append(
            make_evidence_contribution(
                contribution_id="heat_disagreement_gate",
                source_class="system",
                source_name="cross_source_agreement",
                role="limitation",
                summary="Regional or neighborhood heat context is stronger than the local node reading, so parcel heat interpretation remains cautious.",
                hazards=["heat"],
                weight=disagreement["weight"],
            )
        )

    return contributions


def confidence_band(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


def build_explanation_payload(
    *,
    confidence: float,
    evidence_mode: str,
    inference_basis: str,
    evidence_contributions: list[dict],
    divergence_records: list[dict],
    contrastive_explanations: list[dict],
    support_objects_present: list[str],
    parcel_context: dict | None,
    shared_context: dict | None,
    public_context: dict | None,
) -> dict:
    sorted_drivers = sorted(
        (item for item in evidence_contributions if item["role"] == "driver"),
        key=lambda item: item["weight"],
        reverse=True,
    )
    sorted_limitations = sorted(
        (item for item in evidence_contributions if item["role"] == "limitation"),
        key=lambda item: item["weight"],
        reverse=True,
    )
    drivers = [item["summary"] for item in sorted_drivers[:3]]
    limitations = [item["summary"] for item in sorted_limitations[:3]]
    if not limitations:
        limitations = ["Evidence limits are currently low enough that few explicit caveats were generated."]

    headline = (
        f"Estimate uses {inference_basis.replace('_', ' ')} evidence with "
        f"{confidence_band(confidence)} confidence."
    )

    return {
        "headline": headline,
        "basis": {
            "evidence_mode": evidence_mode,
            "inference_basis": inference_basis,
            "confidence_band": confidence_band(confidence),
        },
        "drivers": drivers,
        "limitations": limitations,
        "evidence_contributions": evidence_contributions,
        "source_breakdown": {
            "local": True,
            "shared": shared_context is not None,
            "public": public_context is not None,
            "parcel_context": parcel_context is not None,
            "system": any(item["source_class"] == "system" for item in evidence_contributions),
        },
        "support_objects_present": support_objects_present,
        "divergence_summary": [item["contrast"]["summary"] for item in contrastive_explanations[:2]],
        "top_divergence_records": divergence_records[:3],
    }


def infer_parcel_state(
    payload: dict,
    *,
    computed_at: str | None = None,
    runtime_lane: str | None = None,
    parcel_context: dict | None = None,
    house_state: dict | None = None,
    house_capability: dict | None = None,
    equipment_state_observation: dict | None = None,
    source_provenance_record: dict | None = None,
    intervention_event: dict | None = None,
    verification_outcome: dict | None = None,
    shared_neighborhood_context: dict | None = None,
    public_context: dict | None = None,
) -> dict:
    resolved_lane = resolve_runtime_lane(runtime_lane)
    validate_normalized_observation(payload)
    if parcel_context is not None:
        validate_parcel_context(parcel_context)
    if house_state is not None:
        validate_house_state(house_state)
    if house_capability is not None:
        validate_house_capability(house_capability)
    if equipment_state_observation is not None:
        validate_equipment_state_observation(equipment_state_observation)
    if source_provenance_record is not None:
        validate_source_provenance_record(source_provenance_record)
    if intervention_event is not None:
        validate_intervention_event(intervention_event)
    if verification_outcome is not None:
        validate_verification_outcome(verification_outcome)
    if shared_neighborhood_context is not None:
        validate_shared_neighborhood_signal(shared_neighborhood_context)
    if public_context is not None:
        validate_public_context(public_context)

    now = parse_time(computed_at) if computed_at else datetime.now(timezone.utc)
    computed_at = (computed_at or now_iso())
    observed_at = parse_time(payload["observed_at"])
    age_seconds = max(0, int((now - observed_at).total_seconds()))
    stale = age_seconds > 900
    context = classify_local_context(payload, parcel_context=parcel_context)

    shared_context = build_shared_neighborhood_context(shared_neighborhood_context) if shared_neighborhood_context else None
    parcel_prior_details = build_parcel_prior_details(parcel_context)

    hazards = derive_hazards(
        payload,
        parcel_context=parcel_context,
        house_state=house_state,
        house_capability=house_capability,
        verification_outcome=verification_outcome,
        shared_neighborhood_context=shared_context,
        public_context=public_context,
        now=now,
    )
    confidence = derive_confidence(
        payload,
        hazards,
        now=now,
        parcel_context=parcel_context,
        house_state=house_state,
        house_capability=house_capability,
        intervention_event=intervention_event,
        verification_outcome=verification_outcome,
        shared_neighborhood_context=shared_context,
        public_context=public_context,
    )
    status_config = _hazard_thresholds()["status_mapping"]
    state_rules = _hazard_thresholds()["state_rules"]
    status_snapshot = build_state_snapshot(
        hazards=hazards,
        context=context,
        confidence=confidence,
        stale=stale,
        status_config=status_config,
        state_rules=state_rules,
        status_from_probability=status_from_probability,
    )

    evidence_mode = "local_only"
    has_nonexpired_public_context = False
    if public_context:
        member_contexts = public_context.get("members", [public_context])
        has_nonexpired_public_context = any(
            public_context_freshness_band(member, now=now) != "expired" for member in member_contexts
        )

    if public_context and has_nonexpired_public_context and not stale and confidence >= state_rules["insufficient_confidence_floor"]:
        evidence_mode = "local_plus_public"
    if stale or confidence < state_rules["insufficient_confidence_floor"]:
        evidence_mode = "insufficient"

    inference_basis = "local_only"
    if stale or confidence < state_rules["insufficient_confidence_floor"]:
        inference_basis = "insufficient"
    elif shared_context and has_nonexpired_public_context:
        inference_basis = "local_plus_shared_plus_public"
    elif shared_context:
        inference_basis = "local_plus_shared"
    elif has_nonexpired_public_context:
        inference_basis = "local_plus_public"

    public_only_hazards, _ = derive_public_baseline_hazards(
        parcel_context=parcel_context,
        house_capability=house_capability,
        verification_outcome=verification_outcome,
        shared_context=shared_context,
        public_context=public_context,
        now=now,
        public_context_freshness_band=public_context_freshness_band,
        get_policy_for_source=get_policy_for_source,
    )
    public_only_confidence = derive_public_baseline_confidence(
        payload=payload,
        hazards=public_only_hazards,
        now=now,
        parcel_context=parcel_context,
        house_capability=house_capability,
        verification_outcome=verification_outcome,
        shared_context=shared_context,
        public_context=public_context,
        public_context_freshness_band=public_context_freshness_band,
        get_policy_for_source=get_policy_for_source,
    )
    public_only_statuses = build_state_snapshot(
        hazards=public_only_hazards,
        context=context,
        confidence=public_only_confidence,
        stale=stale,
        status_config=status_config,
        state_rules=state_rules,
        status_from_probability=status_from_probability,
    )
    divergence_records = build_divergence_records(
        payload=payload,
        parcel_context=parcel_context,
        house_state=house_state,
        public_context=public_context,
    )
    contrastive_explanations = build_contrastive_explanations(
        payload=payload,
        computed_at=computed_at,
        parcel_context=parcel_context,
        house_state=house_state,
        house_capability=house_capability,
        public_context=public_context,
        shared_context=shared_context,
        fact_hazards=hazards,
        fact_confidence=confidence,
        fact_statuses=status_snapshot,
        foil_hazards=public_only_hazards,
        foil_confidence=public_only_confidence,
        foil_statuses=public_only_statuses,
        divergence_records=divergence_records,
    )

    evidence_contributions = build_evidence_contributions(
        payload=payload,
        parcel_context=parcel_context,
        parcel_prior_details=parcel_prior_details,
        house_state=house_state,
        house_capability=house_capability,
        equipment_state_observation=equipment_state_observation,
        source_provenance_record=source_provenance_record,
        intervention_event=intervention_event,
        verification_outcome=verification_outcome,
        shared_context=shared_context,
        public_context=public_context,
        divergence_records=divergence_records,
        hazards=hazards,
        confidence=confidence,
        stale=stale,
        now=now,
    )
    support_objects_present = [
        name
        for name, obj in (
            ("house_state", house_state),
            ("house_capability", house_capability),
            ("equipment_state_observation", equipment_state_observation),
            ("source_provenance_record", source_provenance_record),
            ("intervention_event", intervention_event),
            ("verification_outcome", verification_outcome),
        )
        if obj is not None
    ]
    closed_loop_summary = build_closed_loop_summary(
        house_state=house_state,
        intervention_event=intervention_event,
        verification_outcome=verification_outcome,
        smoke_config=_hazard_thresholds()["smoke"],
    )
    reasons = derive_reasons(
        payload,
        confidence,
        evidence_contributions,
        parcel_context=parcel_context,
        public_context=public_context,
        parcel_prior_details=parcel_prior_details,
        contrastive_explanations=contrastive_explanations,
    )
    explanation_payload = build_explanation_payload(
        confidence=confidence,
        evidence_mode=evidence_mode,
        inference_basis=inference_basis,
        evidence_contributions=evidence_contributions,
        divergence_records=divergence_records,
        contrastive_explanations=contrastive_explanations,
        support_objects_present=support_objects_present,
        parcel_context=parcel_context,
        shared_context=shared_context,
        public_context=public_context,
    )

    source_modes = [payload["provenance"]["source_kind"]]
    if shared_context:
        source_modes.append(shared_context["source_kind"])
    if public_context:
        source_modes.append(public_context["source_kind"])
    if support_objects_present:
        source_modes.append("private_support_object")

    return {
        "parcel_id": payload["parcel_id"],
        "computed_at": computed_at,
        "versioning": versioning_payload(lane=resolved_lane),
        "shelter_status": status_snapshot["shelter_status"],
        "reentry_status": status_snapshot["reentry_status"],
        "egress_status": status_snapshot["egress_status"],
        "asset_risk_status": status_snapshot["asset_risk_status"],
        "confidence": confidence,
        "evidence_mode": evidence_mode,
        "inference_basis": inference_basis,
        "explanation_payload": explanation_payload,
        "reasons": reasons,
        "hazards": hazards,
        "hazard_statuses": {
            "smoke": status_snapshot["smoke_status"],
            "heat": status_snapshot["heat_status"],
            "flood": status_snapshot["flood_status"],
        },
        "parcel_priors_applied": parcel_prior_details,
        "divergence_records": divergence_records,
        "public_only_counterfactual": {
            "hazards": public_only_hazards,
            "hazard_statuses": {
                "smoke": public_only_statuses["smoke_status"],
                "heat": public_only_statuses["heat_status"],
                "flood": public_only_statuses["flood_status"],
            },
            "confidence": public_only_confidence,
        },
        "closed_loop_summary": closed_loop_summary,
        "contrastive_explanations": contrastive_explanations,
        "freshness": {
            "latest_observation_at": payload["observed_at"],
            "seconds_since_latest": age_seconds,
            "stale": stale,
        },
        "provenance_summary": {
            "observation_count": 1,
            "source_modes": source_modes,
            "runtime_lane": resolved_lane,
            "observation_refs": [
                payload["observation_id"]
            ],
            "support_object_refs": support_objects_present,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infer a parcel-state snapshot from a normalized observation.")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(EXAMPLES_DIR / "normalized-observation.example.json"),
        help="Path to a normalized observation JSON file.",
    )
    parser.add_argument(
        "--computed-at",
        default=None,
        help="Optional RFC 3339 timestamp to use as the computation time.",
    )
    parser.add_argument(
        "--runtime-lane",
        default=None,
        help="Optional runtime lane (for example v0.1, v1.0).",
    )
    parser.add_argument(
        "--parcel-context",
        default=None,
        help="Optional path to a parcel context JSON file to combine with local evidence.",
    )
    parser.add_argument("--house-state", default=None, help="Optional path to a house-state JSON file.")
    parser.add_argument("--house-capability", default=None, help="Optional path to a house-capability JSON file.")
    parser.add_argument(
        "--equipment-state-observation",
        default=None,
        help="Optional path to an equipment-state-observation JSON file.",
    )
    parser.add_argument(
        "--source-provenance-record",
        default=None,
        help="Optional path to a source-provenance-record JSON file.",
    )
    parser.add_argument("--intervention-event", default=None, help="Optional path to an intervention-event JSON file.")
    parser.add_argument("--verification-outcome", default=None, help="Optional path to a verification-outcome JSON file.")
    parser.add_argument(
        "--shared-neighborhood-signal",
        default=None,
        help="Optional path to a shared neighborhood signal JSON file to combine with local evidence.",
    )
    parser.add_argument(
        "--public-context",
        action="append",
        default=[],
        help="Optional path to a public context JSON file to combine with local evidence. May be passed more than once.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()

    try:
        payload = load_json(input_path)
        parcel_context = load_json(Path(args.parcel_context).resolve()) if args.parcel_context else None
        house_state = load_json(Path(args.house_state).resolve()) if args.house_state else None
        house_capability = load_json(Path(args.house_capability).resolve()) if args.house_capability else None
        equipment_state_observation = (
            load_json(Path(args.equipment_state_observation).resolve()) if args.equipment_state_observation else None
        )
        source_provenance_record = (
            load_json(Path(args.source_provenance_record).resolve()) if args.source_provenance_record else None
        )
        intervention_event = load_json(Path(args.intervention_event).resolve()) if args.intervention_event else None
        verification_outcome = load_json(Path(args.verification_outcome).resolve()) if args.verification_outcome else None
        shared_neighborhood_signal = (
            load_json(Path(args.shared_neighborhood_signal).resolve())
            if args.shared_neighborhood_signal
            else None
        )
        public_contexts = [load_json(Path(path).resolve()) for path in args.public_context]
        public_context = combine_public_contexts(public_contexts)
        result = infer_parcel_state(
            payload,
            computed_at=args.computed_at,
            runtime_lane=args.runtime_lane,
            parcel_context=parcel_context,
            house_state=house_state,
            house_capability=house_capability,
            equipment_state_observation=equipment_state_observation,
            source_provenance_record=source_provenance_record,
            intervention_event=intervention_event,
            verification_outcome=verification_outcome,
            shared_neighborhood_context=shared_neighborhood_signal,
            public_context=public_context,
        )
    except (InferenceError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR {input_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
