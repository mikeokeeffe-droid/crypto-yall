"""Staging-only restart recovery: unresolved intents are never retried."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Recovery:
    action: str
    reason: str

def classify_restart(intent_status, owned, flat, no_open_orders, fresh):
    if not fresh or any(type(v) is not bool for v in (owned, flat, no_open_orders)):
        return Recovery("hold", "missing or stale evidence")
    if owned and (flat or not no_open_orders):
        return Recovery("hold", "conflicting ownership or open-order evidence")
    if owned:
        return Recovery("manage_existing", "existing owned position")
    if intent_status in ("pending", "submitted", "uncertain", "filled"):
        return Recovery("hold", "unresolved intent")
    if not flat or not no_open_orders:
        return Recovery("hold", "position or open order present")
    if intent_status in ("rejected_final", "released"):
        return Recovery("inspect_only", "eligible for manual inspection")
    return Recovery("hold", "unknown intent")
