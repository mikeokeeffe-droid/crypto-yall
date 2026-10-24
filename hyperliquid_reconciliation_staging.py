"""Staging-only Hyperliquid order evidence classifier.

Accepts injected, already-fetched exchange responses. Does NOT connect to
Hyperliquid, change ownership, resolve an intent, or submit orders.
An API failure, partial fill, ambiguous response or stale snapshot is UNKNOWN.
"""
from dataclasses import dataclass
from enum import Enum


class ReconcileState(Enum):
    FILLED = "filled"
    REJECTED_FINAL_FLAT = "rejected_final_flat"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReconcileEvidence:
    state: ReconcileState
    reason: str


def classify_order_evidence(*, order_response: dict | None,
                            position_snapshot: dict | None,
                            open_orders_snapshot: list | None,
                            expected_coin: str,
                            expected_order_id: str | None = None,
                            snapshots_fresh: bool = False) -> ReconcileEvidence:
    if (not snapshots_fresh or not expected_coin or
            not isinstance(order_response, dict) or
            not isinstance(position_snapshot, dict) or
            not isinstance(open_orders_snapshot, list)):
        return ReconcileEvidence(ReconcileState.UNKNOWN, "missing or stale evidence")
    if position_snapshot.get("coin") != expected_coin:
        return ReconcileEvidence(ReconcileState.UNKNOWN, "position coin mismatch")
    if expected_order_id is not None and str(order_response.get("oid", "")) != str(expected_order_id):
        return ReconcileEvidence(ReconcileState.UNKNOWN, "order id mismatch")
    if any(not isinstance(o, dict) or o.get("coin") == expected_coin
           for o in open_orders_snapshot):
        return ReconcileEvidence(ReconcileState.UNKNOWN, "outstanding or ambiguous order")
    status = order_response.get("status")
    if status == "filled":
        try:
            fill_size = float(order_response["filled_size"])
            position_size = float(position_snapshot["size"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return ReconcileEvidence(ReconcileState.UNKNOWN, "invalid fill or position size")
        if fill_size > 0 and position_size != 0 and expected_order_id is not None:
            return ReconcileEvidence(ReconcileState.FILLED, "matching fill and non-flat position")
        return ReconcileEvidence(ReconcileState.UNKNOWN, "fill lacks confirmed ownership evidence")
    if status == "rejected" and order_response.get("final") is True:
        try:
            position_size = float(position_snapshot["size"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return ReconcileEvidence(ReconcileState.UNKNOWN, "missing position size")
        if position_size == 0:
            return ReconcileEvidence(ReconcileState.REJECTED_FINAL_FLAT, "final rejection and flat position")
    return ReconcileEvidence(ReconcileState.UNKNOWN, "ambiguous exchange outcome")
