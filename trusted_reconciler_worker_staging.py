"""Staging-only independent reconciliation coordinator.

This service core receives exchange evidence through an injected read-only Info
client. It never submits trades or uses a routine executor database identity.
Durable database transitions must be performed by a separately authenticated
trusted worker only after an allowed decision. No production deployment here.
"""
from dataclasses import dataclass
from hyperliquid_reconciliation_pipeline_staging import evaluate_handoff, evaluate_release

@dataclass(frozen=True)
class ReconciliationResult:
    action: str
    reason: str

def reconcile_entry(info, address, *, coin, order_id, order_start_ms, clock):
    if (type(order_id) not in (str, int) or not str(order_id).strip()
            or (type(order_id) is int and order_id < 0)):
        return ReconciliationResult("hold", "missing exchange order identity")
    if type(order_start_ms) is not int or order_start_ms < 0:
        return ReconciliationResult("hold", "missing durable submission timestamp")
    decision = evaluate_handoff(info, address, coin=coin, order_id=order_id,
                                order_start_ms=order_start_ms, clock=clock)
    if not decision.allowed:
        return ReconciliationResult("hold", decision.reason)
    return ReconciliationResult("handoff_candidate", "exchange evidence verified; trusted database transaction still required")

def reconcile_closed(info, address, *, coin, clock):
    decision = evaluate_release(info, address, coin=coin, clock=clock)
    if not decision.allowed:
        return ReconciliationResult("hold", decision.reason)
    return ReconciliationResult("release_candidate", "flat snapshot verified; trusted database transaction still required")
