"""Offline-only dispatch lifecycle model: no SDK, network, locks or trade permissions.

Models the safety rule that an attempted send must never be automatically
replayed or reassigned. This is NOT a distributed sender or a live lock.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class DispatchDecision:
    state: str
    permitted: bool
    reason: str

def review_dispatch_transition(*, current_state, event, fence, current_fence):
    """Fail closed on unknown states, stale fences and ambiguous sends."""
    if (type(fence) is not int or type(current_fence) is not int
            or fence <= 0 or current_fence <= 0 or fence != current_fence):
        return DispatchDecision("hold", False, "stale or invalid fence")
    transitions = {
        ("reserved", "prepare"): "prepared",
        ("prepared", "mark_dispatch_unknown"): "dispatch_unknown",
        ("dispatch_unknown", "observed"): "observed_unverified",
    }
    next_state = transitions.get((current_state, event))
    if next_state is None:
        return DispatchDecision("hold", False, "invalid or unsafe transition")
    # State change here is a pure illustration, not permission to send.
    return DispatchDecision(next_state, False, "offline state model only; no dispatch permission")
