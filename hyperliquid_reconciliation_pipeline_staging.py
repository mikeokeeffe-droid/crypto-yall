"""Join independently acquired read-only evidence with offline decisions.

No exchange orders or database mutations. A real trusted reconciler must
own the Info client, verify account identity and handle pagination before
using these decisions for durable ownership transitions.
"""
from dataclasses import dataclass
from hyperliquid_readonly_evidence_staging import fetch_exchange_snapshot, is_fresh
from trusted_reconciliation_staging import verify_handoff, verify_release

@dataclass(frozen=True)
class EvidenceResult:
    allowed: bool
    reason: str

def evaluate_handoff(info, account_address, *, coin, order_id, clock):
    try:
        snapshot = fetch_exchange_snapshot(info, account_address, clock=clock)
        decision = verify_handoff(
            coin=coin, order_id=order_id, fills=snapshot.fills,
            open_orders=snapshot.open_orders, user_state=snapshot.user_state,
            fresh=is_fresh(snapshot, now=clock()),
        )
        return EvidenceResult(decision.allowed, decision.reason)
    except (Exception) as exc:
        return EvidenceResult(False, "exchange evidence unavailable: " + type(exc).__name__)

def evaluate_release(info, account_address, *, coin, clock):
    try:
        snapshot = fetch_exchange_snapshot(info, account_address, clock=clock)
        decision = verify_release(
            coin=coin, open_orders=snapshot.open_orders,
            user_state=snapshot.user_state,
            fresh=is_fresh(snapshot, now=clock()),
        )
        return EvidenceResult(decision.allowed, decision.reason)
    except (Exception) as exc:
        return EvidenceResult(False, "exchange evidence unavailable: " + type(exc).__name__)
