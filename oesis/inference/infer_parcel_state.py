#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from oesis.common.repo_paths import DOCS_EXAMPLES_DIR, INFERENCE_CONFIG_DIR

EXAMPLES_DIR = DOCS_EXAMPLES_DIR
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


def load_public_context_policy() -> dict:
    return load_json(PUBLIC_CONTEXT_POLICY_PATH)


PUBLIC_CONTEXT_POLICY = load_public_context_policy()


def load_hazard_thresholds() -> dict:
    return load_json(HAZARD_THRESHOLDS_PATH)


HAZARD_THRESHOLDS = load_hazard_thresholds()


def load_trust_gates() -> dict:
    return load_json(TRUST_GATES_PATH)


TRUST_GATES = load_trust_gates()


def get_policy_for_source(source_name: str) -> dict:
    default_policy = PUBLIC_CONTEXT_POLICY["default_policy"]
    override = PUBLIC_CONTEXT_POLICY.get("source_overrides", {}).get(source_name, {})
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
    shared_neighborhood_context: dict | None = None,
    public_context: dict | None = None,
    *,
    now: datetime,
) -> dict:
    values = payload["values"]
    health = payload["health"]
    context = classify_local_context(payload, parcel_context=parcel_context)
    smoke_config = HAZARD_THRESHOLDS["smoke"]
    heat_config = HAZARD_THRESHOLDS["heat"]
    sensor_penalties = HAZARD_THRESHOLDS["sensor_penalties"]
    parcel_priors = parcel_context.get("parcel_priors", {}) if parcel_context else {}

    smoke_probability = smoke_config["base_probability"]
    gas_resistance = values.get("gas_resistance_ohm")
    smoke_probability = probability_from_lt_bands(
        gas_resistance,
        smoke_config["gas_resistance_bands"],
        smoke_config["default_probability"],
    )

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

    heat_probability += prior_adjustment(parcel_priors.get("heat_retention_class"))
    smoke_probability += prior_adjustment(parcel_priors.get("smoke_exposure_class"), low=-0.01, moderate=0.0, high=0.03)

    flood_probability = 0.0

    if not health.get("wifi_connected", False):
        smoke_probability -= sensor_penalties["wifi_disconnected"]
        heat_probability -= sensor_penalties["wifi_disconnected"]

    if health.get("read_failures_total", 0) > 0:
        smoke_probability -= sensor_penalties["read_failures"]
        heat_probability -= sensor_penalties["read_failures"]

    if public_context:
        member_contexts = public_context.get("members", [public_context])
        for member in member_contexts:
            freshness_band = public_context_freshness_band(member, now=now)
            policy = get_policy_for_source(member["source_name"])
            public_hazards = member["hazards"]
            multiplier = policy["hazard_multiplier"][freshness_band]
            smoke_probability = max(smoke_probability, round(public_hazards["smoke_probability"] * multiplier, 2))
            heat_probability = max(heat_probability, round(public_hazards["heat_probability"] * multiplier, 2))
            flood_probability = max(flood_probability, round(public_hazards["flood_probability"] * multiplier, 2))

    if shared_neighborhood_context:
        shared_hazards = shared_neighborhood_context["hazards"]
        smoke_probability = max(smoke_probability, round(shared_hazards["smoke_probability"] * 0.55, 2))
        heat_probability = max(heat_probability, round(shared_hazards["heat_probability"] * 0.45, 2))
        flood_probability = max(flood_probability, round(shared_hazards["flood_probability"] * 0.4, 2))

    return {
        "smoke_probability": clamp_probability(smoke_probability),
        "flood_probability": clamp_probability(flood_probability),
        "heat_probability": clamp_probability(heat_probability),
    }


def derive_confidence(
    payload: dict,
    hazards: dict,
    *,
    now: datetime,
    parcel_context: dict | None = None,
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
) -> list[str]:
    reasons = []
    context = classify_local_context(payload, parcel_context=parcel_context)
    parcel_priors = parcel_context.get("parcel_priors", {}) if parcel_context else {}

    for contribution in evidence_contributions[:6]:
        reasons.append(contribution["summary"])

    if parcel_priors.get("heat_retention_class") == "high":
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
        reasons.append("The current decision is based on a single homeowner-owned node without confirming public context.")

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
    visibility: str = "homeowner_safe",
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
    shared_context: dict | None,
    public_context: dict | None,
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
                weight=TRUST_GATES["freshness_gate"]["stale_weight"],
            )
        )

    if confidence < TRUST_GATES["confidence_gate"]["low_confidence_threshold"]:
        contributions.append(
            make_evidence_contribution(
                contribution_id="low_confidence_gate",
                source_class="system",
                source_name="confidence_gate",
                role="limitation",
                summary="Confidence is limited because the current estimate relies on sparse or weakly representative evidence.",
                hazards=["smoke", "heat", "flood"],
                weight=TRUST_GATES["confidence_gate"]["weight"],
            )
        )

    public_members = public_context.get("members", [public_context]) if public_context else []
    strongest_public_smoke = max((member["hazards"]["smoke_probability"] for member in public_members), default=0.0)
    strongest_public_heat = max((member["hazards"]["heat_probability"] for member in public_members), default=0.0)
    strongest_shared_smoke = shared_context["hazards"]["smoke_probability"] if shared_context else 0.0
    strongest_shared_heat = shared_context["hazards"]["heat_probability"] if shared_context else 0.0

    disagreement = TRUST_GATES["cross_source_disagreement"]

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
    }


def infer_parcel_state(
    payload: dict,
    *,
    computed_at: str | None = None,
    parcel_context: dict | None = None,
    shared_neighborhood_context: dict | None = None,
    public_context: dict | None = None,
) -> dict:
    validate_normalized_observation(payload)
    if parcel_context is not None:
        validate_parcel_context(parcel_context)
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

    hazards = derive_hazards(
        payload,
        parcel_context=parcel_context,
        shared_neighborhood_context=shared_context,
        public_context=public_context,
        now=now,
    )
    confidence = derive_confidence(
        payload,
        hazards,
        now=now,
        parcel_context=parcel_context,
        shared_neighborhood_context=shared_context,
        public_context=public_context,
    )
    status_config = HAZARD_THRESHOLDS["status_mapping"]
    state_rules = HAZARD_THRESHOLDS["state_rules"]

    smoke_status = status_from_probability(
        hazards["smoke_probability"],
        unknown_floor=status_config["default_unknown_floor"],
    )
    heat_status = status_from_probability(
        hazards["heat_probability"],
        unknown_floor=status_config["heat_unknown_floor"],
    )
    flood_status = status_from_probability(
        hazards["flood_probability"],
        unknown_floor=status_config["flood_unknown_floor"],
    )

    shelter_status = "unknown"
    if max(hazards["smoke_probability"], hazards["heat_probability"]) >= state_rules["shelter_hazard_floor"] and confidence >= state_rules["shelter_confidence_floor"]:
        shelter_status = smoke_status if hazards["smoke_probability"] >= hazards["heat_probability"] else heat_status
    elif heat_status == "caution" and not context["is_indoor"] and confidence >= state_rules["heat_caution_confidence_floor"]:
        shelter_status = "caution"

    reentry_status = "unknown"
    egress_status = "unknown"
    asset_risk_status = "unknown"

    if not context["is_indoor"] and max(hazards.values()) >= state_rules["asset_risk_hazard_floor"] and confidence >= state_rules["asset_risk_confidence_floor"]:
        asset_risk_status = "caution"

    if not context["is_indoor"] and max(hazards.values()) >= state_rules["egress_hazard_floor"] and confidence >= state_rules["egress_confidence_floor"]:
        egress_status = "caution"

    if flood_status == "caution" and confidence >= 0.5:
        asset_risk_status = "caution"

    if stale and confidence < 0.6:
        shelter_status = "unknown"
        reentry_status = "unknown"
        egress_status = "unknown"
        asset_risk_status = "unknown"

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

    evidence_contributions = build_evidence_contributions(
        payload=payload,
        parcel_context=parcel_context,
        shared_context=shared_context,
        public_context=public_context,
        hazards=hazards,
        confidence=confidence,
        stale=stale,
        now=now,
    )
    reasons = derive_reasons(
        payload,
        confidence,
        evidence_contributions,
        parcel_context=parcel_context,
        public_context=public_context,
    )
    explanation_payload = build_explanation_payload(
        confidence=confidence,
        evidence_mode=evidence_mode,
        inference_basis=inference_basis,
        evidence_contributions=evidence_contributions,
        parcel_context=parcel_context,
        shared_context=shared_context,
        public_context=public_context,
    )

    source_modes = [payload["provenance"]["source_kind"]]
    if shared_context:
        source_modes.append(shared_context["source_kind"])
    if public_context:
        source_modes.append(public_context["source_kind"])

    return {
        "parcel_id": payload["parcel_id"],
        "computed_at": computed_at,
        "shelter_status": shelter_status,
        "reentry_status": reentry_status,
        "egress_status": egress_status,
        "asset_risk_status": asset_risk_status,
        "confidence": confidence,
        "evidence_mode": evidence_mode,
        "inference_basis": inference_basis,
        "explanation_payload": explanation_payload,
        "reasons": reasons,
        "hazards": hazards,
        "freshness": {
            "latest_observation_at": payload["observed_at"],
            "seconds_since_latest": age_seconds,
            "stale": stale,
        },
        "provenance_summary": {
            "observation_count": 1,
            "source_modes": source_modes,
            "observation_refs": [
                payload["observation_id"]
            ],
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
        "--parcel-context",
        default=None,
        help="Optional path to a parcel context JSON file to combine with local evidence.",
    )
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
            parcel_context=parcel_context,
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
