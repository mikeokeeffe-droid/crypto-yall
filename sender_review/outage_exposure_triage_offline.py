"""Synthetic incident triage for PR #42: never a live safety controller.

An offline decision aid for reviewing an outage/position-protection runbook.
NO network, exchange SDK, wallet, host, database, alert sending or order I/O.
Inputs are entirely untrusted synthetic observations. It cannot confirm
flatness, close a trade, attest an operator, or authorize a restart/cutover.
ALL returned states are NO_GO and ALWAYS require human review.
"""
from dataclasses import dataclass

_EVENTS = frozenset((
    "sender_unavailable", "collector_unavailable",
    "protective_close_failed", "unknown_ack",
    "partial_fill", "position_owner_disputed",
    "alerting_unavailable", "rollback_requested",
))
_EXPOSURES = frozenset(("open", "flat", "unknown"))
_PROTECTION = frozenset(("reported_healthy", "failed", "unknown"))


@dataclass(frozen=True)
class SyntheticOutageIncident:
    """Caller assertions only; no authenticated or exchange-derived evidence."""
    event: str
    exposure: str
    protection: str
    history_complete: bool
    on_call_acknowledged: bool
    alert_paths_tested: bool
    unresolved_attempt: bool
    original_writers_revoked: bool
    single_writer_verified: bool


@dataclass(frozen=True)
class OutageTriageReview:
    state: str = "NO_GO"
    severity: str = "CRITICAL"
    reason: str = "untrusted-or-incomplete-incident-fixture"
    stop_new_entries: bool = True
    stop_new_pyramids: bool = True
    retain_unknown_attempt_fences: bool = True
    human_response_required: bool = True
    emergency_rescue_required: bool = True
    fixture_coherent: bool = False
    # The fixture cannot prove that a protective close, host or operator
    # really exists. NEVER report trade or rollback approval.
    real_position_verified: bool = False
    protective_coverage_verified: bool = False
    runtime_alert_delivered: bool = False
    operator_ack_verified: bool = False
    fence_released: bool = False
    retry_authorized: bool = False
    close_authorized: bool = False
    rollback_authorized: bool = False
    trade_authorized: bool = False
    signing_enabled: bool = False


def review_outage_exposure_fixture_offline(incident) -> OutageTriageReview:
    """Conservative *synthetic* triage, not an operational response.

    Even an apparently complete "flat and healthy" fixture remains NO_GO.
    A reported open/unknown position with a sender/protection outage must
    not be counted as safely protected. Unknown acknowledgement retains
    the proposed hold irrespective of caller-provided "flat" data.
    """
    hold = OutageTriageReview()
    if type(incident) is not SyntheticOutageIncident:
        return hold
    if (type(incident.event) is not str or incident.event not in _EVENTS
            or type(incident.exposure) is not str
            or incident.exposure not in _EXPOSURES
            or type(incident.protection) is not str
            or incident.protection not in _PROTECTION
            or any(type(getattr(incident, field)) is not bool for field in (
                "history_complete", "on_call_acknowledged",
                "alert_paths_tested", "unresolved_attempt",
                "original_writers_revoked", "single_writer_verified",
            ))):
        return hold

    acute_event = incident.event in (
        "sender_unavailable", "collector_unavailable",
        "protective_close_failed", "unknown_ack", "partial_fill",
    )
    exposed = incident.exposure in ("open", "unknown")
    protection_gap = incident.protection in ("failed", "unknown")
    human_or_telemetry_gap = (
        not incident.history_complete
        or not incident.on_call_acknowledged
        or not incident.alert_paths_tested
    )
    contradictory_writers = (
        not incident.original_writers_revoked
        or not incident.single_writer_verified
    )
    critical = (
        (exposed and (acute_event or protection_gap))
        or incident.event == "protective_close_failed"
        or incident.unresolved_attempt
        or (exposed and human_or_telemetry_gap)
        or (exposed and contradictory_writers)
        or incident.event == "alerting_unavailable"
    )
    if critical:
        reason = "possible-unprotected-exposure-requires-human-risk-escalation"
    elif contradictory_writers:
        reason = "single-writer-cutover-unverified"
    else:
        reason = "no-independent-runtime-exchange-or-rescue-evidence"
    return OutageTriageReview(
        severity="CRITICAL" if critical else "REVIEW_REQUIRED",
        reason=reason,
        emergency_rescue_required=critical,
        fixture_coherent=True,
    )
