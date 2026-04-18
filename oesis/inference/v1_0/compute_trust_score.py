"""Compute a parcel-level trust score from signal-level quality factors.

Trust score measures **measurement trust** (input quality), distinct from
parcel-state confidence (conclusion quality). A parcel can have high trust
(fresh, calibrated, well-installed sensors) but low confidence (ambiguous
evidence), or vice versa.

Contract: https://github.com/lumenaut-llc/oesis-contracts/blob/main/v1.0/trust-score-schema.md
Schema:   https://github.com/lumenaut-llc/oesis-contracts/blob/main/v1.0/schemas/trust-score.schema.json
"""

from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Factor weights (must sum to 1.0)
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS = {
    "freshness": 0.30,
    "node_health": 0.25,
    "calibration_state": 0.20,
    "install_quality": 0.10,
    "source_diversity": 0.15,
}

# ---------------------------------------------------------------------------
# Band thresholds
# ---------------------------------------------------------------------------

def _band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "medium"
    if score >= 0.25:
        return "low"
    return "degraded"


# ---------------------------------------------------------------------------
# Individual factor scorers
# ---------------------------------------------------------------------------

def _score_freshness(
    payload: dict,
    *,
    now: datetime,
    public_context: dict | None = None,
) -> tuple[float, str, list[dict]]:
    """Score freshness from local observation age and public context age.

    Fresh (≤30m) = 1.0, Aging (30m–2h) = 0.7, Stale (2–6h) = 0.3,
    Expired (>6h) = 0.0
    """
    penalties = []
    observed_at = datetime.fromisoformat(payload["observed_at"].replace("Z", "+00:00"))
    local_age_seconds = max(0, int((now - observed_at).total_seconds()))

    if local_age_seconds <= 1800:
        local_score = 1.0
        local_desc = f"local node fresh ({local_age_seconds // 60}m)"
    elif local_age_seconds <= 7200:
        local_score = 0.7
        local_desc = f"local node aging ({local_age_seconds // 60}m)"
        penalties.append({
            "factor_key": "freshness",
            "penalty": round(1.0 - 0.7, 2),
            "reason": f"Local observation aging ({local_age_seconds // 60}m old)",
            "applied_at": now.isoformat().replace("+00:00", "Z"),
        })
    elif local_age_seconds <= 21600:
        local_score = 0.3
        local_desc = f"local node stale ({local_age_seconds // 60}m)"
        penalties.append({
            "factor_key": "freshness",
            "penalty": round(1.0 - 0.3, 2),
            "reason": f"Local observation stale ({local_age_seconds // 60}m old)",
            "applied_at": now.isoformat().replace("+00:00", "Z"),
        })
    else:
        local_score = 0.0
        local_desc = f"local node expired ({local_age_seconds // 3600}h)"
        penalties.append({
            "factor_key": "freshness",
            "penalty": 1.0,
            "reason": f"Local observation expired ({local_age_seconds // 3600}h old)",
            "applied_at": now.isoformat().replace("+00:00", "Z"),
        })

    # Check public context freshness
    public_score = None
    public_desc = ""
    if public_context:
        members = public_context.get("members", [public_context])
        ages = []
        for member in members:
            ts = member.get("observed_at") or member.get("retrieved_at")
            if ts:
                member_age = max(0, int((now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()))
                ages.append(member_age)
        if ages:
            worst_age = max(ages)
            if worst_age <= 1800:
                public_score = 1.0
            elif worst_age <= 7200:
                public_score = 0.7
                penalties.append({
                    "factor_key": "freshness",
                    "penalty": round(1.0 - 0.7, 2),
                    "reason": f"Public context aging ({worst_age // 60}m old)",
                    "applied_at": now.isoformat().replace("+00:00", "Z"),
                })
            elif worst_age <= 21600:
                public_score = 0.3
            else:
                public_score = 0.0

    # Combine: use worst of local and public
    if public_score is not None:
        score = min(local_score, public_score)
        reason = f"Public context and {local_desc}"
    else:
        score = local_score
        reason = local_desc.capitalize()

    return score, reason, penalties


def _score_node_health(payload: dict) -> tuple[float, str, list[dict]]:
    """Score from health indicators in the observation.

    Nominal = 1.0, Minor degradation = 0.7, Significant = 0.3, Offline = 0.0
    """
    penalties = []
    health = payload.get("health", {})

    read_failures = health.get("read_failures_total", 0)
    wifi = health.get("wifi_connected", True)
    uptime = health.get("uptime_seconds", 86400)

    if read_failures == 0 and wifi and uptime > 300:
        return 1.0, "All health indicators nominal", penalties

    score = 1.0
    reasons = []

    if read_failures > 0:
        score -= 0.3
        reasons.append(f"{read_failures} read failure(s)")
        penalties.append({
            "factor_key": "node_health",
            "penalty": 0.3,
            "reason": f"Read failures detected ({read_failures})",
            "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })

    if not wifi:
        score -= 0.2
        reasons.append("WiFi disconnected")

    if uptime < 300:
        score -= 0.1
        reasons.append("recently restarted")

    score = max(0.0, score)
    reason = "; ".join(reasons) if reasons else "All health indicators nominal"

    return round(score, 2), reason, penalties


def _score_calibration_state(
    payload: dict,
    *,
    source_provenance_record: dict | None = None,
) -> tuple[float, str, list[dict]]:
    """Score from calibration state.

    Verified = 1.0, Provisional = 0.6, Needs service = 0.2, Unsupported = 0.0
    """
    penalties = []

    # Check provenance record first (most authoritative)
    cal_state = None
    if source_provenance_record:
        cal_state = source_provenance_record.get("calibration_state")

    # Fall back to observation provenance
    if cal_state is None:
        provenance = payload.get("provenance", {})
        registry_meta = provenance.get("registry_metadata", {})
        cal_state = registry_meta.get("calibration_state")

    # Fall back to values
    if cal_state is None:
        cal_state = payload.get("values", {}).get("calibration_state")

    scores = {
        "verified": (1.0, "Verified calibration"),
        "recently_calibrated": (0.9, "Recently calibrated"),
        "provisional": (0.6, "Provisional calibration (awaiting field verification)"),
        "needs_service": (0.2, "Calibration needs service"),
        "unsupported": (0.0, "Calibration unsupported"),
    }

    if cal_state in scores:
        score, reason = scores[cal_state]
        if score < 0.75:
            penalties.append({
                "factor_key": "calibration_state",
                "penalty": round(1.0 - score, 2),
                "reason": reason,
                "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })
        return score, reason, penalties

    # Unknown calibration — treat as provisional
    return 0.6, "Calibration state unknown; provisional score applied", penalties


def _score_install_quality(
    payload: dict,
    *,
    parcel_context: dict | None = None,
    source_provenance_record: dict | None = None,
) -> tuple[float, str, list[dict]]:
    """Score from deployment metadata / install quality.

    Field-validated = 1.0, Standard = 0.7, Provisional = 0.4,
    No metadata = 0.5 (neutral, not penalizing)
    """
    penalties = []

    # Check source provenance for install status
    install_status = None
    if source_provenance_record:
        install_status = source_provenance_record.get("install_status")

    # Check provenance registry metadata
    if install_status is None:
        registry_meta = payload.get("provenance", {}).get("registry_metadata", {})
        install_status = registry_meta.get("install_status")

    # Check parcel context for deployment metadata
    has_deployment_meta = False
    if parcel_context:
        installations = parcel_context.get("node_installations", [])
        node_id = payload.get("node_id")
        for inst in installations:
            if inst.get("node_id") == node_id:
                if inst.get("mount_type") or inst.get("install_height_cm"):
                    has_deployment_meta = True
                break

    scores = {
        "field_validated": (1.0, "Field-validated installation"),
        "standard": (0.7, "Standard installation"),
        "provisional": (0.4, "Provisional installation"),
    }

    if install_status in scores:
        score, reason = scores[install_status]
        return score, reason, penalties

    if has_deployment_meta:
        return 0.7, "Deployment metadata available; standard score", penalties

    # No metadata — neutral
    return 0.5, "No deployment metadata available; neutral score applied", penalties


def _score_source_diversity(
    payload: dict,
    *,
    public_context: dict | None = None,
    shared_context: dict | None = None,
) -> tuple[float, str, list[dict]]:
    """Score from evidence source diversity.

    Local + public + shared = 1.0, Local + public = 0.8, Local only = 0.6,
    Public only = 0.3
    """
    has_local = payload.get("provenance", {}).get("source_kind") == "direct_measurement"
    has_public = public_context is not None
    has_shared = shared_context is not None

    if has_local and has_public and has_shared:
        return 1.0, "Local, public, and shared context all contributing", []
    if has_local and has_public:
        return 0.8, "Local node and public context both contributing", []
    if has_local:
        return 0.6, "Local node only; no public or shared context", []
    if has_public:
        return 0.3, "Public context only; no local node", []
    return 0.1, "No evidence sources identified", []


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_trust_score(
    payload: dict,
    *,
    now: datetime | None = None,
    parcel_context: dict | None = None,
    source_provenance_record: dict | None = None,
    public_context: dict | None = None,
    shared_context: dict | None = None,
) -> dict:
    """Compute a trust score for a parcel observation.

    Returns a dict matching the trust-score schema:
    - parcel_id, scored_at, overall_band, overall_score
    - factors: array of per-factor breakdowns
    - penalty_log: ordered penalties applied
    """
    if now is None:
        now = datetime.now(timezone.utc)

    scored_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    all_penalties: list[dict] = []
    factors: list[dict] = []

    # Compute each factor
    scorers = [
        ("freshness", lambda: _score_freshness(payload, now=now, public_context=public_context)),
        ("node_health", lambda: _score_node_health(payload)),
        ("calibration_state", lambda: _score_calibration_state(payload, source_provenance_record=source_provenance_record)),
        ("install_quality", lambda: _score_install_quality(payload, parcel_context=parcel_context, source_provenance_record=source_provenance_record)),
        ("source_diversity", lambda: _score_source_diversity(payload, public_context=public_context, shared_context=shared_context)),
    ]

    for factor_key, scorer in scorers:
        score, reason, penalties = scorer()
        factors.append({
            "factor_key": factor_key,
            "weight": FACTOR_WEIGHTS[factor_key],
            "score": round(score, 2),
            "band": _band(score),
            "reason": reason,
        })
        all_penalties.extend(penalties)

    # Composite score: weighted average
    total_weight = sum(f["weight"] for f in factors)
    overall_score = sum(f["weight"] * f["score"] for f in factors) / total_weight if total_weight > 0 else 0.0
    overall_score = round(overall_score, 2)

    return {
        "parcel_id": payload.get("parcel_id", "unknown"),
        "scored_at": scored_at,
        "overall_band": _band(overall_score),
        "overall_score": overall_score,
        "factors": factors,
        "penalty_log": all_penalties,
    }
