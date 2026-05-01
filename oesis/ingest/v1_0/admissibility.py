"""
Admissibility-decision computation for normalized observations (G15).

Per ADR 0009 in oesis-program-specs (schema carries facts, runtime computes
decision), this module implements the calibration-program §C and
adapter-trust-program §C admissibility rules. The fact fields it consumes
land on canonical observations via:

  - oesis-contracts v1.0 node-observation (G17, calibration §C facts)
  - oesis-contracts v1.5 source-provenance-record (G18, adapter §C facts)

The output of compute_admissibility() is attached to NORMALIZED observations
only — never back-propagated to the canonical observation schema.

This module is intentionally pure and side-effect-free:
- No I/O, no time lookups inside the rule body, no DB calls.
- Cadence/freshness checks compare two timestamps the caller supplies.
- The caller (typically normalize_packet.py) is responsible for collecting
  the facts dict and passing in the comparison "now" / cadence threshold.

Sources of truth:
  - calibration-program §C — physical-sensor 8-point check
  - adapter-trust-program §C — adapter-derived 8-point check
  - The reason codes returned here MUST stay in lockstep with what those
    docs publish, so downstream UX surfacing matches the policy's wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# --- Reason codes (calibration-program §C) ---
REASON_NODE_IDENTITY_MISSING = "node_identity_missing"
REASON_DEPLOYMENT_MATURITY_INSUFFICIENT = "deployment_maturity_insufficient"
REASON_DEPLOYMENT_CLASS_MISMATCH = "deployment_class_mismatch"
REASON_BURN_IN_INCOMPLETE = "burn_in_incomplete"
REASON_REFERENCE_CALIBRATION_STALE = "reference_calibration_stale"
REASON_REPRESENTATIVENESS_CLASS_D = "representativeness_class_d"
REASON_FIXTURE_UNVERIFIED = "fixture_unverified"
REASON_SENSOR_HEALTH_DEGRADED = "sensor_health_degraded"

# --- Reason codes (adapter-trust-program §C) ---
REASON_ADAPTER_SOURCE_MISSING = "adapter_source_missing"
REASON_CONTRACT_VERSION_DRIFT = "contract_version_drift"
REASON_ONBOARDING_MISSING = "onboarding_missing"
REASON_CREDENTIALS_EXPIRED = "credentials_expired"
REASON_CADENCE_STALE = "cadence_stale"
REASON_TIER_INSUFFICIENT = "tier_insufficient"
REASON_UNCERTAINTY_OUT_OF_BOUNDS = "uncertainty_out_of_bounds"
REASON_SOURCE_INCIDENT_OPEN = "source_incident_open"

# --- Tier values ---
TIER_1_PASSIVE = "tier_1_passive"
TIER_2_ADAPTER = "tier_2_adapter"
TIER_3_DIRECT = "tier_3_direct"

# --- Deployment maturity ladder ordering (lowest to highest) ---
_MATURITY_ORDER = ["v0.1", "v1.0", "v1.5", "v2.0"]
_MATURITY_RANK = {m: i for i, m in enumerate(_MATURITY_ORDER)}
# Per §C check 2: must be at least v1.0 to be admissible.
_MATURITY_MIN_RANK = _MATURITY_RANK["v1.0"]


@dataclass(frozen=True)
class AdmissibilityResult:
    """Outcome of compute_admissibility().

    `admissible` is True only when reasons is the empty list. Caller MUST
    treat any non-empty reasons list as inadmissible regardless of the
    boolean — they are populated together by this module.
    """

    admissible: bool
    reasons: list[str]


def _parse_iso(ts: Any) -> datetime | None:
    """Best-effort ISO-8601 parse. Returns None on any failure."""
    if not isinstance(ts, str):
        return None
    try:
        # Accept "...Z" by normalizing to +00:00 for fromisoformat.
        normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def compute_admissibility(
    facts: dict[str, Any],
    *,
    tier: str | None = None,
    now: datetime | None = None,
    reference_calibration_max_age_days: int = 90,
    adapter_credential_max_age_days: int = 30,
    adapter_cadence_max_age_days: int = 1,
) -> AdmissibilityResult:
    """
    Compute admissibility for a single observation's fact set.

    Branches on `tier`:
      - None or `tier_3_direct` → calibration-program §C (physical sensor)
      - `tier_1_passive` or `tier_2_adapter` → adapter-trust-program §C

    Args:
      facts: dict of fact field names → values, as carried on the canonical
        observation. For physical-sensor path, expects the v1.0 G17 facts
        plus health/identity. For adapter path, expects the v1.5 G18 facts.
        Missing fact keys are treated per §C (typically a reason code is
        emitted; the function never raises KeyError on a fact lookup).
      tier: which §C ruleset to apply. None defaults to physical-sensor.
      now: current UTC datetime for cadence/freshness comparisons.
        Defaults to datetime.now(timezone.utc); pass an explicit value for
        deterministic tests.
      reference_calibration_max_age_days: cadence for §C check 5
        (calibration-program physical-sensor path).
      adapter_credential_max_age_days: cadence for adapter §C check 4.
      adapter_cadence_max_age_days: cadence for adapter §C check 5.

    Returns:
      AdmissibilityResult(admissible, reasons). admissible is True iff
      reasons is empty.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if tier in (TIER_1_PASSIVE, TIER_2_ADAPTER):
        reasons = _check_adapter_path(
            facts,
            now=now,
            tier=tier,
            credential_max_age_days=adapter_credential_max_age_days,
            cadence_max_age_days=adapter_cadence_max_age_days,
        )
    else:
        reasons = _check_physical_sensor_path(
            facts,
            now=now,
            calibration_max_age_days=reference_calibration_max_age_days,
        )

    return AdmissibilityResult(admissible=not reasons, reasons=reasons)


# --------------------------------------------------------------------------
# Physical-sensor path (calibration-program §C, 8 checks)
# --------------------------------------------------------------------------

def _check_physical_sensor_path(
    facts: dict[str, Any],
    *,
    now: datetime,
    calibration_max_age_days: int,
) -> list[str]:
    reasons: list[str] = []

    # 1. Node identity is current.
    if not facts.get("node_id") or not facts.get("firmware_version"):
        reasons.append(REASON_NODE_IDENTITY_MISSING)

    # 2. Deployment maturity tier met (>= v1.0).
    maturity = facts.get("node_deployment_maturity")
    rank = _MATURITY_RANK.get(maturity, -1)
    if rank < _MATURITY_MIN_RANK:
        reasons.append(REASON_DEPLOYMENT_MATURITY_INSUFFICIENT)

    # 3. Deployment class honored. The producer-side intent (location_mode)
    #    must agree with the verified install attribute (node_deployment_class).
    #    Disagreement is a real signal, not a benign mismatch.
    location_mode = facts.get("location_mode")
    deployment_class = facts.get("node_deployment_class")
    if (
        location_mode is not None
        and deployment_class is not None
        and location_mode != deployment_class
    ):
        reasons.append(REASON_DEPLOYMENT_CLASS_MISMATCH)
    elif deployment_class is None:
        # No verified install attribute on the packet at all is also
        # a §C #3 failure — admissibility requires the class be declared.
        reasons.append(REASON_DEPLOYMENT_CLASS_MISMATCH)

    # 4. Burn-in complete.
    if not facts.get("burn_in_complete"):
        reasons.append(REASON_BURN_IN_INCOMPLETE)

    # 5. Reference calibration current.
    cal_ref = facts.get("node_calibration_session_ref")
    cal_at = _parse_iso(facts.get("node_calibration_verified_at"))
    if not cal_ref:
        reasons.append(REASON_REFERENCE_CALIBRATION_STALE)
    elif cal_at is not None:
        # If the caller surfaced a calibration timestamp, enforce cadence.
        # If absent, the presence of node_calibration_session_ref alone
        # does NOT prove freshness — caller is responsible for stamping
        # node_calibration_verified_at when it can resolve the session.
        age_days = (now - cal_at).total_seconds() / 86400
        if age_days > calibration_max_age_days:
            reasons.append(REASON_REFERENCE_CALIBRATION_STALE)

    # 6. Placement representativeness declared, not Class D.
    representativeness = facts.get("placement_representativeness_class")
    if representativeness == "D":
        reasons.append(REASON_REPRESENTATIVENESS_CLASS_D)
    elif representativeness is None:
        # §C #6 says class must be declared. Null is not a pass.
        reasons.append(REASON_REPRESENTATIVENESS_CLASS_D)

    # 7. Protective fixtures verified where required. For outdoor class,
    #    protective_fixture_verified_at must be a non-null timestamp.
    if deployment_class == "outdoor":
        if facts.get("protective_fixture_verified_at") is None:
            reasons.append(REASON_FIXTURE_UNVERIFIED)
    # Indoor / sheltered: fixture verification not required by policy.

    # 8. Sensor health within bounds at observation time.
    health = facts.get("health") or {}
    read_failures = health.get("read_failures_total")
    if isinstance(read_failures, int) and read_failures > 0:
        # Threshold is currently strict (any failures since boot is degraded).
        # A future PR can swap this for a rate threshold per §C #8 cadence.
        reasons.append(REASON_SENSOR_HEALTH_DEGRADED)

    return reasons


# --------------------------------------------------------------------------
# Adapter path (adapter-trust-program §C, 8 checks)
# --------------------------------------------------------------------------

def _check_adapter_path(
    facts: dict[str, Any],
    *,
    now: datetime,
    tier: str | None,
    credential_max_age_days: int,
    cadence_max_age_days: int,
) -> list[str]:
    reasons: list[str] = []

    # 1. Source authority registered.
    if not facts.get("adapter_source_ref"):
        reasons.append(REASON_ADAPTER_SOURCE_MISSING)

    # 2. API contract version matches pinned version. The adapter's reported
    #    contract version must equal the source file's pinned version. Caller
    #    can either pre-resolve and pass facts["adapter_contract_version_pinned"]
    #    matching adapter_contract_version, OR simply omit the pinned field —
    #    in that case we accept the adapter's stated version on faith. A future
    #    PR will tighten this once the source-authority lookup is wired.
    reported = facts.get("adapter_contract_version")
    pinned = facts.get("adapter_contract_version_pinned")
    if not reported:
        reasons.append(REASON_CONTRACT_VERSION_DRIFT)
    elif pinned is not None and pinned != reported:
        reasons.append(REASON_CONTRACT_VERSION_DRIFT)

    # 3. Onboarding gate passed for this parcel.
    if not facts.get("adapter_onboarding_ref"):
        reasons.append(REASON_ONBOARDING_MISSING)

    # 4. Credentials current.
    cred_at = _parse_iso(facts.get("adapter_credential_last_verified_at"))
    if cred_at is None:
        reasons.append(REASON_CREDENTIALS_EXPIRED)
    else:
        age_days = (now - cred_at).total_seconds() / 86400
        if age_days > credential_max_age_days:
            reasons.append(REASON_CREDENTIALS_EXPIRED)

    # 5. Cadence honored. Observation must arrive within the documented
    #    refresh cadence; stale beyond cadence_max_age_days is inadmissible.
    observed_at = _parse_iso(facts.get("observed_at"))
    if observed_at is not None:
        observation_age_days = (now - observed_at).total_seconds() / 86400
        if observation_age_days > cadence_max_age_days:
            reasons.append(REASON_CADENCE_STALE)
    # observed_at absence isn't an adapter §C failure on its own — it would
    # be caught by an earlier validation layer.

    # 6. Tier-appropriate confidence. Only tier_2_adapter and tier_1_passive
    #    can legitimately reach this branch (the caller routed here on tier).
    #    Surface a tier_insufficient code when tier is the explicit string
    #    "insufficient" or unrecognized; the contract enum covers the
    #    legitimate cases.
    if tier not in (TIER_1_PASSIVE, TIER_2_ADAPTER):
        # Caller routing error or an explicit "tier insufficient" sentinel.
        reasons.append(REASON_TIER_INSUFFICIENT)

    # 7. Source-derived uncertainty within bounds. If the adapter provides
    #    its own uncertainty/confidence and the spec declares a bound, check
    #    it. Both fields are optional; this is a best-effort gate.
    uncertainty = facts.get("adapter_uncertainty")
    bound = facts.get("adapter_uncertainty_bound")
    if (
        isinstance(uncertainty, (int, float))
        and isinstance(bound, (int, float))
        and uncertainty > bound
    ):
        reasons.append(REASON_UNCERTAINTY_OUT_OF_BOUNDS)

    # 8. No open adapter incident.
    if facts.get("adapter_incident_open") is True:
        reasons.append(REASON_SOURCE_INCIDENT_OPEN)

    return reasons
