from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from oesis.common.repo_paths import INFERENCE_CONFIG_DIR

DIVERGENCE_RULES_PATH = INFERENCE_CONFIG_DIR / "divergence_rules_v0.json"
PARCEL_PRIOR_RULES_PATH = INFERENCE_CONFIG_DIR / "parcel_prior_rules_v0.json"


def parse_time(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def clamp_range(value: float, *, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@lru_cache(maxsize=1)
def _divergence_rules() -> dict:
    return json.loads(Path(DIVERGENCE_RULES_PATH).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _parcel_prior_rules() -> dict:
    return json.loads(Path(PARCEL_PRIOR_RULES_PATH).read_text(encoding="utf-8"))


def barkjohn_correct(pa_cf1: float, rh: float) -> float:
    config = _divergence_rules()["parameters"]["pm25"]["barkjohn_2021"]
    return round(
        config["slope"] * pa_cf1
        + config["rh_coeff"] * rh
        + config["intercept"],
        2,
    )


def _lookup_band_multiplier(value: float | None, bands: list[dict]) -> float:
    if value is None:
        return 1.0
    for band in bands:
        minimum = band.get("min", float("-inf"))
        maximum = band.get("max", float("inf"))
        lt = band.get("lt")
        if lt is not None:
            maximum = lt
        if minimum <= value < maximum:
            return band["multiplier"]
    return bands[-1]["multiplier"] if bands else 1.0


def _lookup_year_band(year: int | None, bands: list[dict]) -> tuple[float, str | None]:
    if year is None:
        return 1.0, None
    for band in bands:
        minimum = band.get("min", float("-inf"))
        maximum = band.get("max", float("inf"))
        if minimum <= year <= maximum:
            return band["multiplier"], band.get("label")
    return 1.0, None


def _smoke_prior_details(parcel_priors: dict) -> dict:
    rules = _parcel_prior_rules()["smoke"]
    exposure_class = parcel_priors.get("smoke_exposure_class", "unknown")
    probability = rules["base_probability"].get(exposure_class, rules["base_probability"]["unknown"])
    factors = []
    if exposure_class != "unknown":
        factors.append(
            {
                "factor": "smoke_exposure_class",
                "value": exposure_class,
                "effect": "baseline_probability",
                "applied_value": round(probability, 4),
            }
        )

    for field_name, config_key in (
        ("zone_zero_clearance_class", "zone_zero_clearance_class"),
        ("defensible_space_class", "defensible_space_class"),
        ("roof_class", "roof_class"),
        ("exterior_class", "exterior_class"),
        ("vent_class", "vent_class"),
        ("window_class", "window_class"),
    ):
        value = parcel_priors.get(field_name)
        if value is None:
            continue
        multiplier = _parcel_prior_rules()["smoke"][config_key].get(value, 1.0)
        probability *= multiplier
        factors.append(
            {
                "factor": field_name,
                "value": value,
                "effect": "multiplier",
                "applied_value": round(multiplier, 4),
            }
        )

    dist_to_wildland_ft = parcel_priors.get("dist_to_wildland_ft")
    if dist_to_wildland_ft is not None:
        multiplier = _lookup_band_multiplier(dist_to_wildland_ft, rules["distance_to_wildland_ft"])
        probability *= multiplier
        factors.append(
            {
                "factor": "dist_to_wildland_ft",
                "value": dist_to_wildland_ft,
                "effect": "multiplier",
                "applied_value": round(multiplier, 4),
            }
        )

    probability = clamp_range(
        probability,
        minimum=rules["min_probability"],
        maximum=rules["max_probability"],
    )
    adjustment = clamp_range(
        probability - rules["baseline_probability"],
        minimum=rules["adjustment_min"],
        maximum=rules["adjustment_max"],
    )
    summary = (
        f"Parcel metadata sets a smoke prior at {probability:.2f} "
        f"from exposure class '{exposure_class}'."
    )
    return {
        "probability": round(probability, 4),
        "adjustment": round(adjustment, 4),
        "summary": summary,
        "factors": factors,
    }


def _heat_prior_details(parcel_priors: dict) -> dict:
    rules = _parcel_prior_rules()["heat"]["adjustments"]
    heat_class = parcel_priors.get("heat_retention_class", "unknown")
    adjustment = rules.get(heat_class, rules["unknown"])
    summary = (
        "Parcel metadata does not materially change the heat prior."
        if adjustment == 0
        else f"Parcel metadata applies a {adjustment:+.2f} heat prior from retention class '{heat_class}'."
    )
    factors = []
    if heat_class != "unknown":
        factors.append(
            {
                "factor": "heat_retention_class",
                "value": heat_class,
                "effect": "adjustment",
                "applied_value": round(adjustment, 4),
            }
        )
    return {
        "probability": None,
        "adjustment": round(adjustment, 4),
        "summary": summary,
        "factors": factors,
    }


def _flood_prior_details(parcel_priors: dict) -> dict:
    rules = _parcel_prior_rules()["flood"]
    zone = parcel_priors.get("fema_zone", "X_unshaded")
    probability = rules["base_zones"].get(zone, rules["min_probability"])
    factors = [
        {
            "factor": "fema_zone",
            "value": zone,
            "effect": "baseline_probability",
            "applied_value": round(probability, 4),
        }
    ]

    foundation_type = parcel_priors.get("foundation_type")
    if foundation_type is not None:
        foundation_multiplier = rules["foundation_type"].get(foundation_type, 1.0)
        probability *= foundation_multiplier
        factors.append(
            {
                "factor": "foundation_type",
                "value": foundation_type,
                "effect": "multiplier",
                "applied_value": round(foundation_multiplier, 4),
            }
        )

    first_floor = parcel_priors.get("first_floor_elev_ft")
    base_flood = parcel_priors.get("base_flood_elev_ft")
    if first_floor is not None and base_flood is not None:
        ffh_delta = first_floor - base_flood
        if ffh_delta > 0:
            elev_multiplier = max(
                rules["freeboard_min_multiplier"],
                1.0 - ffh_delta * rules["freeboard_reduction_per_ft"],
            )
        else:
            elev_multiplier = min(
                rules["below_bfe_max_multiplier"],
                1.0 + abs(ffh_delta) * rules["below_bfe_increase_per_ft"],
            )
        probability *= elev_multiplier
        factors.append(
            {
                "factor": "first_floor_vs_bfe_ft",
                "value": round(ffh_delta, 2),
                "effect": "multiplier",
                "applied_value": round(elev_multiplier, 4),
            }
        )

    year_built = parcel_priors.get("year_built")
    age_multiplier, age_label = _lookup_year_band(year_built, rules["year_built_breakpoints"])
    if year_built is not None:
        probability *= age_multiplier
        factors.append(
            {
                "factor": "year_built",
                "value": year_built,
                "effect": age_label or "multiplier",
                "applied_value": round(age_multiplier, 4),
            }
        )

    dist_to_water_ft = parcel_priors.get("dist_to_water_ft")
    if dist_to_water_ft is not None:
        distance_multiplier = _lookup_band_multiplier(dist_to_water_ft, rules["distance_to_water_ft"])
        probability *= distance_multiplier
        factors.append(
            {
                "factor": "dist_to_water_ft",
                "value": dist_to_water_ft,
                "effect": "multiplier",
                "applied_value": round(distance_multiplier, 4),
            }
        )

    probability = clamp_range(
        probability,
        minimum=rules["min_probability"],
        maximum=rules["max_probability"],
    )
    summary = f"Parcel flood prior resolves to {probability:.3f} from FEMA zone '{zone}' and parcel modifiers."
    return {
        "probability": round(probability, 4),
        "adjustment": None,
        "summary": summary,
        "factors": factors,
    }


def build_parcel_prior_details(parcel_context: dict | None) -> dict:
    parcel_priors = parcel_context.get("parcel_priors", {}) if parcel_context else {}
    return {
        "heat": _heat_prior_details(parcel_priors),
        "smoke": _smoke_prior_details(parcel_priors),
        "flood": _flood_prior_details(parcel_priors),
    }


def _classify_direction(delta: float) -> str:
    if delta > 0:
        return "local_elevated"
    if delta < 0:
        return "local_depressed"
    return "concordant"


def _classify_magnitude(abs_diff: float, thresholds: dict) -> str:
    if abs_diff < thresholds["noise_max"]:
        return "noise"
    if abs_diff < thresholds["low_max"]:
        return "low"
    if abs_diff < thresholds["moderate_max"]:
        return "moderate"
    if abs_diff < thresholds["high_max"]:
        return "high"
    return "extreme"


def _classify_persistence(minutes: int) -> str:
    for rule in _divergence_rules()["persistence_classes"]:
        max_minutes = rule.get("max_minutes")
        if max_minutes is None or minutes <= max_minutes:
            return rule["label"]
    return "chronic"


def _classify_divergence_confidence(*, magnitude: str, persistence_minutes: int, concordant_sensors: int) -> str:
    persistence_class = _classify_persistence(persistence_minutes)
    high_conf_sensors = _divergence_rules()["high_confidence_requires_concordant_sensors"]
    if (
        concordant_sensors >= high_conf_sensors
        and persistence_class in {"sustained", "persistent", "chronic"}
        and magnitude in {"high", "extreme"}
    ):
        return "high"
    if magnitude in {"moderate", "high", "extreme"}:
        return "medium"
    return "low"


def _aqi_category(pm25_value: float | None) -> str | None:
    if pm25_value is None:
        return None
    for index, breakpoint in enumerate(_divergence_rules()["parameters"]["pm25"]["aqi_breakpoints"]):
        maximum = breakpoint.get("max")
        if maximum is None or pm25_value <= maximum:
            return breakpoint["label"]
    return None


def _aqi_ordinal(label: str | None) -> int | None:
    if label is None:
        return None
    for index, breakpoint in enumerate(_divergence_rules()["parameters"]["pm25"]["aqi_breakpoints"]):
        if breakpoint["label"] == label:
            return index
    return None


def _compute_ratio(local_value: float, regional_value: float) -> float | None:
    if regional_value <= 0:
        return None
    return round(local_value / regional_value, 2)


def _build_signal_record(
    *,
    timestamp: str,
    sensor_id: str,
    parameter: str,
    local_value: float,
    regional_value: float,
    regional_source: str,
    correction_applied: str,
    sigma: float,
    persistence_minutes: int,
    concordant_sensors: int,
    local_category: str | None = None,
    regional_category: str | None = None,
) -> dict:
    abs_diff = round(abs(local_value - regional_value), 2)
    delta = round(local_value - regional_value, 2)
    thresholds = _divergence_rules()["parameters"][parameter]["magnitude_thresholds"]
    magnitude = _classify_magnitude(abs_diff, thresholds)
    aqi_diff = None
    if local_category is not None and regional_category is not None:
        local_ordinal = _aqi_ordinal(local_category)
        regional_ordinal = _aqi_ordinal(regional_category)
        if local_ordinal is not None and regional_ordinal is not None:
            aqi_diff = local_ordinal - regional_ordinal
    return {
        "timestamp": timestamp,
        "sensor_id": sensor_id,
        "parameter": parameter,
        "local_value": round(local_value, 2),
        "regional_value": round(regional_value, 2),
        "regional_source": regional_source,
        "correction_applied": correction_applied,
        "abs_diff": abs_diff,
        "ratio": _compute_ratio(local_value, regional_value),
        "z_score": round(abs_diff / sigma, 2) if sigma > 0 else None,
        "direction": _classify_direction(delta),
        "magnitude": magnitude,
        "persistence_minutes": persistence_minutes,
        "persistence_class": _classify_persistence(persistence_minutes),
        "aqi_category_local": local_category,
        "aqi_category_regional": regional_category,
        "aqi_category_diff": aqi_diff,
        "num_concordant_sensors": concordant_sensors,
        "confidence": _classify_divergence_confidence(
            magnitude=magnitude,
            persistence_minutes=persistence_minutes,
            concordant_sensors=concordant_sensors,
        ),
    }


def _find_public_member(public_context: dict | None, raw_field: str) -> tuple[dict | None, dict | None]:
    if public_context is None:
        return None, None
    members = public_context.get("members", [public_context])
    for member in members:
        raw_context = member.get("raw_context")
        if raw_context and raw_field in raw_context:
            return member, raw_context
    raw_context = public_context.get("raw_context")
    if raw_context and raw_field in raw_context:
        return public_context, raw_context
    return None, None


def _divergence_tracking(parcel_context: dict | None, parameter: str) -> tuple[int, int]:
    tracking = (parcel_context or {}).get("divergence_tracking", {})
    entry = tracking.get(parameter, {})
    persistence_minutes = int(entry.get("persistence_minutes", 0))
    concordant_sensors = int(entry.get("num_concordant_sensors", 1))
    return persistence_minutes, concordant_sensors


def _local_pm25(payload: dict, house_state: dict | None) -> tuple[float | None, str, str | None]:
    values = payload.get("values", {})
    sensor_id = payload.get("node_id")
    if values.get("pm25_cf1_ugm3") is not None and values.get("relative_humidity_pct_primary") is not None:
        return (
            barkjohn_correct(values["pm25_cf1_ugm3"], values["relative_humidity_pct_primary"]),
            "barkjohn_2021",
            sensor_id,
        )
    if values.get("pm25_ugm3") is not None:
        return values["pm25_ugm3"], "none", sensor_id
    if house_state is not None:
        node_ids = house_state.get("source_summary", {}).get("node_ids", [])
        return (
            house_state.get("indoor_response", {}).get("pm25_ugm3"),
            "none",
            node_ids[0] if node_ids else "house_state_support",
        )
    return None, "none", sensor_id


def build_divergence_records(
    *,
    payload: dict,
    parcel_context: dict | None,
    house_state: dict | None,
    public_context: dict | None,
) -> list[dict]:
    records = []
    timestamp = payload["observed_at"]

    weather_member, weather_raw = _find_public_member(public_context, "regional_temperature_c")
    if weather_member and weather_raw and payload.get("values", {}).get("temperature_c_primary") is not None:
        persistence_minutes, concordant_sensors = _divergence_tracking(parcel_context, "temperature_c")
        records.append(
            _build_signal_record(
                timestamp=timestamp,
                sensor_id=payload["node_id"],
                parameter="temperature_c",
                local_value=payload["values"]["temperature_c_primary"],
                regional_value=weather_raw["regional_temperature_c"],
                regional_source=weather_member["source_name"],
                correction_applied="none",
                sigma=_divergence_rules()["parameters"]["temperature_c"]["regional_sigma"],
                persistence_minutes=persistence_minutes,
                concordant_sensors=concordant_sensors,
            )
        )

    smoke_member, smoke_raw = _find_public_member(public_context, "regional_pm25_ugm3")
    local_pm25, correction_applied, sensor_id = _local_pm25(payload, house_state)
    if smoke_member and smoke_raw and local_pm25 is not None:
        persistence_minutes, concordant_sensors = _divergence_tracking(parcel_context, "pm25")
        records.append(
            _build_signal_record(
                timestamp=timestamp,
                sensor_id=sensor_id or payload["node_id"],
                parameter="pm25",
                local_value=local_pm25,
                regional_value=smoke_raw["regional_pm25_ugm3"],
                regional_source=smoke_member["source_name"],
                correction_applied=correction_applied,
                sigma=_divergence_rules()["parameters"]["pm25"]["regional_sigma"],
                persistence_minutes=persistence_minutes,
                concordant_sensors=concordant_sensors,
                local_category=_aqi_category(local_pm25),
                regional_category=_aqi_category(smoke_raw["regional_pm25_ugm3"]),
            )
        )

    return records


def apply_public_and_shared_support(
    hazards: dict,
    *,
    public_context: dict | None,
    shared_context: dict | None,
    now: datetime,
    public_context_freshness_band,
    get_policy_for_source,
) -> dict:
    supported = dict(hazards)
    if public_context:
        member_contexts = public_context.get("members", [public_context])
        for member in member_contexts:
            freshness_band = public_context_freshness_band(member, now=now)
            policy = get_policy_for_source(member["source_name"])
            public_hazards = member["hazards"]
            multiplier = policy["hazard_multiplier"][freshness_band]
            supported["smoke_probability"] = max(
                supported["smoke_probability"],
                round(public_hazards["smoke_probability"] * multiplier, 2),
            )
            supported["heat_probability"] = max(
                supported["heat_probability"],
                round(public_hazards["heat_probability"] * multiplier, 2),
            )
            supported["flood_probability"] = max(
                supported["flood_probability"],
                round(public_hazards["flood_probability"] * multiplier, 2),
            )
    if shared_context:
        shared_hazards = shared_context["hazards"]
        supported["smoke_probability"] = max(
            supported["smoke_probability"],
            round(shared_hazards["smoke_probability"] * 0.55, 2),
        )
        supported["heat_probability"] = max(
            supported["heat_probability"],
            round(shared_hazards["heat_probability"] * 0.45, 2),
        )
        supported["flood_probability"] = max(
            supported["flood_probability"],
            round(shared_hazards["flood_probability"] * 0.4, 2),
        )
    return {key: clamp_probability(value) for key, value in supported.items()}


def derive_public_baseline_hazards(
    *,
    parcel_context: dict | None,
    house_capability: dict | None,
    verification_outcome: dict | None,
    shared_context: dict | None,
    public_context: dict | None,
    now: datetime,
    public_context_freshness_band,
    get_policy_for_source,
) -> tuple[dict, dict]:
    prior_details = build_parcel_prior_details(parcel_context)
    hazards = {
        "smoke_probability": clamp_probability(0.08 + prior_details["smoke"]["adjustment"]),
        "heat_probability": clamp_probability(0.08 + prior_details["heat"]["adjustment"]),
        "flood_probability": clamp_probability(prior_details["flood"]["probability"]),
    }
    if house_capability and house_capability.get("capabilities", {}).get("recirculation_available"):
        hazards["smoke_probability"] = clamp_probability(hazards["smoke_probability"] + 0.01)
    if verification_outcome and verification_outcome.get("hazard_type") == "smoke":
        if verification_outcome.get("result_class") == "worsened":
            hazards["smoke_probability"] = clamp_probability(hazards["smoke_probability"] + 0.03)
    hazards = apply_public_and_shared_support(
        hazards,
        public_context=public_context,
        shared_context=shared_context,
        now=now,
        public_context_freshness_band=public_context_freshness_band,
        get_policy_for_source=get_policy_for_source,
    )
    return hazards, prior_details


def derive_public_baseline_confidence(
    *,
    payload: dict,
    hazards: dict,
    now: datetime,
    parcel_context: dict | None,
    house_capability: dict | None,
    verification_outcome: dict | None,
    shared_context: dict | None,
    public_context: dict | None,
    public_context_freshness_band,
    get_policy_for_source,
) -> float:
    observed_at = parse_time(payload["observed_at"])
    age_seconds = max(0, int((now - observed_at).total_seconds()))
    confidence = 0.36
    if parcel_context is not None:
        confidence += 0.08
    if house_capability is not None:
        confidence += 0.02
    if verification_outcome is not None and verification_outcome.get("result_class") != "inconclusive":
        confidence += 0.02
    if age_seconds > 900:
        confidence -= 0.04
    if age_seconds > 3600:
        confidence -= 0.08
    if max(hazards.values()) < 0.2:
        confidence -= 0.04
    if public_context:
        member_contexts = public_context.get("members", [public_context])
        confidence += min(
            0.18,
            sum(
                get_policy_for_source(member["source_name"])["confidence_adjustment"][
                    public_context_freshness_band(member, now=now)
                ]
                for member in member_contexts
            ),
        )
    if shared_context:
        confidence += 0.04
    return clamp_probability(confidence)


def build_state_snapshot(
    *,
    hazards: dict,
    context: dict,
    confidence: float,
    stale: bool,
    status_config: dict,
    state_rules: dict,
    status_from_probability,
) -> dict:
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
    if (
        max(hazards["smoke_probability"], hazards["heat_probability"]) >= state_rules["shelter_hazard_floor"]
        and confidence >= state_rules["shelter_confidence_floor"]
    ):
        shelter_status = smoke_status if hazards["smoke_probability"] >= hazards["heat_probability"] else heat_status
    elif heat_status == "caution" and not context["is_indoor"] and confidence >= state_rules["heat_caution_confidence_floor"]:
        shelter_status = "caution"

    reentry_status = "unknown"
    egress_status = "unknown"
    asset_risk_status = "unknown"

    if (
        not context["is_indoor"]
        and max(hazards.values()) >= state_rules["asset_risk_hazard_floor"]
        and confidence >= state_rules["asset_risk_confidence_floor"]
    ):
        asset_risk_status = "caution"

    if (
        not context["is_indoor"]
        and max(hazards.values()) >= state_rules["egress_hazard_floor"]
        and confidence >= state_rules["egress_confidence_floor"]
    ):
        egress_status = "caution"

    if flood_status == "caution" and confidence >= 0.5:
        asset_risk_status = "caution"

    if stale and confidence < 0.6:
        shelter_status = "unknown"
        reentry_status = "unknown"
        egress_status = "unknown"
        asset_risk_status = "unknown"

    return {
        "smoke_status": smoke_status,
        "heat_status": heat_status,
        "flood_status": flood_status,
        "shelter_status": shelter_status,
        "reentry_status": reentry_status,
        "egress_status": egress_status,
        "asset_risk_status": asset_risk_status,
    }


def _source_names(
    *,
    payload: dict,
    parcel_context: dict | None,
    house_state: dict | None,
    house_capability: dict | None,
    public_context: dict | None,
    shared_context: dict | None,
    include_local: bool,
) -> list[str]:
    names = []
    if include_local:
        names.append(f"local:{payload['node_id']}")
        if house_state is not None:
            names.append("local:house_state")
    if parcel_context is not None:
        names.append("parcel_context")
    if house_capability is not None:
        names.append("parcel_capability")
    if public_context is not None:
        for member in public_context.get("members", [public_context]):
            names.append(f"public:{member['source_name']}")
    if shared_context is not None:
        names.append(f"shared:{shared_context['cell_id']}")
    return names


def _hazard_to_divergence_parameter(hazard_type: str) -> str | None:
    return {
        "smoke": "pm25",
        "heat": "temperature_c",
        "flood": "flood_stage",
    }.get(hazard_type)


def _hazard_probability_key(hazard_type: str) -> str:
    return {
        "smoke": "smoke_probability",
        "heat": "heat_probability",
        "flood": "flood_probability",
    }[hazard_type]


def _hazard_status_key(hazard_type: str) -> str:
    return {
        "smoke": "smoke_status",
        "heat": "heat_status",
        "flood": "flood_status",
    }[hazard_type]


def _hazard_level_ordinal(status: str) -> int:
    return {
        "unknown": 0,
        "safe": 1,
        "caution": 2,
        "unsafe": 3,
    }.get(status, 0)


def _prediction_window_end(computed_at: str, hazard_type: str) -> str:
    parameter = _hazard_to_divergence_parameter(hazard_type)
    minutes = _divergence_rules()["parameters"].get(parameter, {}).get("verification_window_minutes", 240)
    return (
        parse_time(computed_at) + timedelta(minutes=minutes)
    ).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def build_contrastive_explanations(
    *,
    payload: dict,
    computed_at: str,
    parcel_context: dict | None,
    house_state: dict | None,
    house_capability: dict | None,
    public_context: dict | None,
    shared_context: dict | None,
    fact_hazards: dict,
    fact_confidence: float,
    fact_statuses: dict,
    foil_hazards: dict,
    foil_confidence: float,
    foil_statuses: dict,
    divergence_records: list[dict],
) -> list[dict]:
    explanations = []
    divergence_by_parameter = {record["parameter"]: record for record in divergence_records}

    for hazard_type in ("smoke", "heat", "flood"):
        probability_key = _hazard_probability_key(hazard_type)
        status_key = _hazard_status_key(hazard_type)
        delta_probability = round(fact_hazards[probability_key] - foil_hazards[probability_key], 2)
        divergence = divergence_by_parameter.get(_hazard_to_divergence_parameter(hazard_type))
        if divergence is None and abs(delta_probability) < 0.01:
            continue

        fact_status = fact_statuses[status_key]
        foil_status = foil_statuses[status_key]
        divergence_factors = []
        if divergence is not None:
            divergence_factors.append(
                {
                    "factor": divergence["parameter"],
                    "local_value": divergence["local_value"],
                    "public_value": divergence["regional_value"],
                    "contribution_delta": delta_probability,
                    "is_novel_signal": divergence["magnitude"] in {"high", "extreme"},
                }
            )

        summary = (
            f"Public data alone would have classified {hazard_type} as '{foil_status}' "
            f"(p={foil_hazards[probability_key]:.2f}), while fused parcel inference classified it as "
            f"'{fact_status}' (p={fact_hazards[probability_key]:.2f})."
        )
        if divergence is not None:
            summary += (
                f" Local evidence diverged by {divergence['abs_diff']:.1f} "
                f"and was {divergence['direction']} relative to the regional baseline."
            )

        explanations.append(
            {
                "explanation_id": f"{payload['observation_id']}:{hazard_type}:contrast",
                "timestamp": computed_at,
                "hazard_type": hazard_type,
                "fact": {
                    "conclusion": fact_status,
                    "hazard_level": fact_status,
                    "probability": fact_hazards[probability_key],
                    "confidence": fact_confidence,
                    "data_sources": _source_names(
                        payload=payload,
                        parcel_context=parcel_context,
                        house_state=house_state,
                        house_capability=house_capability,
                        public_context=public_context,
                        shared_context=shared_context,
                        include_local=True,
                    ),
                },
                "foil": {
                    "conclusion": foil_status,
                    "hazard_level": foil_status,
                    "probability": foil_hazards[probability_key],
                    "confidence": foil_confidence,
                    "data_sources": _source_names(
                        payload=payload,
                        parcel_context=parcel_context,
                        house_state=house_state,
                        house_capability=house_capability,
                        public_context=public_context,
                        shared_context=shared_context,
                        include_local=False,
                    ),
                },
                "contrast": {
                    "summary": summary,
                    "delta_hazard_level": _hazard_level_ordinal(fact_status) - _hazard_level_ordinal(foil_status),
                    "delta_probability": delta_probability,
                    "divergence_factors": divergence_factors,
                },
                "verification": {
                    "prediction_window_end": _prediction_window_end(computed_at, hazard_type),
                    "ground_truth_available": False,
                    "scores": {
                        "brier_score_fact": None,
                        "brier_score_foil": None,
                        "local_data_added_value": None,
                    },
                },
            }
        )

    return explanations
