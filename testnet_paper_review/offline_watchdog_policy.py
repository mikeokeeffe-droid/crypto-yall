"""Offline-only watchdog policy rehearsal: no I/O, timers, alerts or orders.

An independent supervisor and authenticated alert delivery remain necessary.
A healthy sample does not clear a prior incident. State is in memory only.
"""
from dataclasses import dataclass
from math import isfinite

MAX_SAMPLE_GAP_S = 30
MAX_OBSERVATION_AGE_S = 10

@dataclass(frozen=True)
class WatchdogState:
    last_tick: float | None = None
    last_sample: float | None = None
    incident: str | None = None
    severity: str = "HOLD"
    may_trade: bool = False

def _valid_time(value):
    return type(value) in (float, int) and isfinite(value) and value >= 0

def advance(state, *, now, sampled_at=None, outcome=None):
    """Pure monotonic-clock policy; external supervisor must call on each tick.

    outcome is an offline fixture classification, not authenticated evidence.
    A missing tick cannot be detected until a later call; external heartbeat
    supervision is mandatory. No incident-reset method is provided.
    """
    if type(state) is not WatchdogState:
        raise ValueError("invalid rehearsal state")
    if not _valid_time(now) or (
        state.last_tick is not None and now < state.last_tick
    ):
        return WatchdogState(state.last_tick, state.last_sample,
                             state.incident or "INVALID_CLOCK", "CRITICAL")
    incident = state.incident
    if state.last_tick is not None and now - state.last_tick > MAX_SAMPLE_GAP_S:
        incident = incident or "SUPERVISOR_TICK_MISSED"
    previous = state.last_sample
    if previous is not None and now - previous > MAX_SAMPLE_GAP_S:
        incident = incident or "OBSERVATION_GAP"
    severity = "HOLD"
    if outcome is None:
        if sampled_at is not None:
            incident = incident or "INVALID_SAMPLE"
        if previous is None:
            incident = incident or "NO_INITIAL_OBSERVATION"
    elif (not _valid_time(sampled_at) or not 0 <= now - sampled_at <= MAX_OBSERVATION_AGE_S
          or (previous is not None and sampled_at <= previous)):
        incident = incident or "STALE_OR_REPLAYED_OBSERVATION"
    elif outcome not in ("FLAT", "BRACKET_OBSERVED", "UNVERIFIED", "UNKNOWN_ACK",
                         "MISSING_STOP", "FOREIGN_EXPOSURE", "EMERGENCY_ATTEMPT",
                         "READ_FAILED"):
        incident = incident or "INVALID_SAMPLE"
    else:
        previous = sampled_at
        if outcome not in ("FLAT", "BRACKET_OBSERVED"):
            incident = incident or outcome
        if outcome == "BRACKET_OBSERVED":
            severity = "ATTENTION"
    if incident is not None:
        severity = "CRITICAL"
    return WatchdogState(now, previous, incident, severity)

def rehearsal_alert(state):
    """Produce a synthetic escalation intent, never deliver a notification."""
    if type(state) is not WatchdogState:
        raise ValueError("invalid rehearsal state")
    if state.incident is not None:
        return "CRITICAL_OPERATOR_INSPECTION_NO_RETRY"
    if state.severity == "ATTENTION":
        return "CONTINUE_MONITORING_NO_STOP_GUARANTEE"
    return "HOLD_NO_TRADING_AUTHORITY"
