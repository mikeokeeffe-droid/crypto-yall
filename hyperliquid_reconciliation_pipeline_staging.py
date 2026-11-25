"""Join independently acquired read-only evidence with offline decisions.

No exchange orders or database mutations. A real trusted reconciler must
own the Info client, verify account identity and handle pagination before
using these decisions for durable ownership transitions.
"""
from dataclasses import dataclass
from math import isfinite
from hyperliquid_readonly_evidence_staging import fetch_exchange_snapshot, is_fresh
from trusted_reconciliation_staging import verify_handoff, verify_release
from hyperliquid_fill_pagination_staging import fetch_fills_window
from hyperliquid_order_status_staging import (
    FINAL_STATUSES,
    read_order_status,
)

@dataclass(frozen=True)
class EvidenceResult:
    allowed: bool
    reason: str

def _read_resolution_evidence(info, account_address, *, coin, order_id,
                              order_start_ms, requested_size, clock):
    status = read_order_status(
        info, account_address, coin=coin, order_id=order_id
    )
    if status not in FINAL_STATUSES:
        return None, EvidenceResult(False, "exchange order is not authoritatively final")
    if type(requested_size) not in (int, float) or requested_size <= 0:
        return None, EvidenceResult(False, "valid requested order size required")
    snapshot = fetch_exchange_snapshot(info, account_address, clock=clock)
    window = fetch_fills_window(
        info,
        account_address,
        order_start_ms,
        int(clock() * 1000),
    )
    if not window.complete:
        return None, EvidenceResult(False, "fill history incomplete: " + window.reason)
    if not is_fresh(snapshot, now=clock()):
        return None, EvidenceResult(False, "exchange snapshot stale after fill pagination")
    matching = [
        fill for fill in window.fills
        if fill.get("coin") == coin and str(fill.get("oid")) == str(order_id)
    ]
    try:
        fill_sizes = [float(fill["sz"]) for fill in matching]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, EvidenceResult(False, "invalid matching fill size")
    if any(not isfinite(size) or size <= 0 for size in fill_sizes):
        return None, EvidenceResult(False, "invalid matching fill size")
    filled_size = sum(fill_sizes)
    if not isfinite(filled_size) or filled_size > float(requested_size):
        return None, EvidenceResult(False, "matching fill size exceeds requested order")
    return (status, snapshot, window, filled_size), EvidenceResult(
        True, "final order and complete fill history verified"
    )


def evaluate_handoff(info, account_address, *, coin, order_id, clock,
                     order_start_ms=None, requested_size=None):
    try:
        if order_start_ms is None:
            return EvidenceResult(False, 'order start time required for complete fill evidence')
        evidence, decision = _read_resolution_evidence(
            info,
            account_address,
            coin=coin,
            order_id=order_id,
            order_start_ms=order_start_ms,
            requested_size=requested_size,
            clock=clock,
        )
        if not decision.allowed:
            return decision
        _, snapshot, window, _ = evidence
        verified = verify_handoff(
            coin=coin,
            order_id=order_id,
            fills=window.fills,
            open_orders=snapshot.open_orders,
            user_state=snapshot.user_state,
            fresh=is_fresh(snapshot, now=clock()),
        )
        return EvidenceResult(verified.allowed, verified.reason)
    except Exception as exc:
        return EvidenceResult(False, "exchange evidence unavailable: " + type(exc).__name__)


def evaluate_unfilled_entry(info, account_address, *, coin, order_id,
                            order_start_ms, requested_size, clock):
    try:
        evidence, acquisition = _read_resolution_evidence(
            info,
            account_address,
            coin=coin,
            order_id=order_id,
            order_start_ms=order_start_ms,
            requested_size=requested_size,
            clock=clock,
        )
        if not acquisition.allowed:
            return acquisition
        status, snapshot, window, filled_size = evidence
        if status in ("filled",) or filled_size != 0:
            return EvidenceResult(False, "order has fills; ownership must be reconciled")
        if status not in ("canceled", "cancelled", "rejected", "expired"):
            return EvidenceResult(False, "order status does not authorize no-fill release")
        del window
        decision = verify_release(
            coin=coin,
            open_orders=snapshot.open_orders,
            user_state=snapshot.user_state,
            fresh=is_fresh(snapshot, now=clock()),
        )
        return EvidenceResult(
            decision.allowed,
            decision.reason if not decision.allowed else "final no-fill order and flat position verified",
        )
    except Exception as exc:
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
