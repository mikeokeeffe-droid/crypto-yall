"""Offline-only rehearsal of emergency alert delivery and acknowledgement.

No notification transport, secrets, network, files or trading. A callback
is intentionally absent; the caller provides synthetic delivery outcomes.
Transport acknowledgement is never human acknowledgement or incident clearance.
"""
from dataclasses import dataclass
from testnet_paper_review.offline_watchdog_policy import WatchdogState

@dataclass(frozen=True)
class AlertReview:
    primary: str
    secondary: str
    operator_acknowledged: bool = False
    incident_cleared: bool = False
    may_trade: bool = False

def review_delivery(state, *, primary_result=None, secondary_result=None):
    if (type(state) is not WatchdogState or state.may_trade is not False
            or state.severity not in ("HOLD", "ATTENTION", "CRITICAL")
            or ((state.incident is None) != (state.severity != "CRITICAL"))):
        return AlertReview("INVALID_STATE_CRITICAL", "INDEPENDENT_ESCALATION_REQUIRED")
    if state.incident is None:
        if primary_result is not None or secondary_result is not None:
            return AlertReview("UNEXPECTED_DELIVERY_RESULT", "INDEPENDENT_ESCALATION_REQUIRED")
        return AlertReview("NO_CRITICAL_INCIDENT", "NONE")
    if primary_result == "TRANSPORT_ACK" and secondary_result is None:
        return AlertReview("TRANSPORT_ACK_NOT_HUMAN_ACK", "HUMAN_ACK_STILL_REQUIRED")
    if primary_result == "TRANSPORT_ACK":
        return AlertReview("INCONSISTENT_DELIVERY_RESULT", "INDEPENDENT_ESCALATION_REQUIRED")
    if secondary_result == "TRANSPORT_ACK":
        return AlertReview("PRIMARY_UNCONFIRMED", "SECONDARY_TRANSPORT_ACK_NOT_HUMAN_ACK")
    return AlertReview("PRIMARY_UNCONFIRMED", "SECONDARY_UNCONFIRMED_CRITICAL")

