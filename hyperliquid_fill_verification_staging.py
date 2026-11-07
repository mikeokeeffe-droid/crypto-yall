"""Offline Hyperliquid fill-record verification; no network or trading.

Consume externally fetched user_fills and open-order snapshots. A missing,
stale, or contradictory snapshot is never proof that an entry can be released.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FillEvidence:
    verified: bool
    filled_size: float = 0.0
    reason: str = ""


def verify_order_fills(*, fills, coin: str, order_id: str,
                       snapshot_fresh: bool, open_orders) -> FillEvidence:
    if (not snapshot_fresh or not coin or not order_id
            or not isinstance(fills, list) or not isinstance(open_orders, list)):
        return FillEvidence(False, reason="missing or stale exchange snapshot")
    if any(not isinstance(order, dict) for order in open_orders):
        return FillEvidence(False, reason="ambiguous outstanding orders")
    if any(order.get("coin") == coin for order in open_orders):
        return FillEvidence(False, reason="coin has outstanding order")
    matching = [f for f in fills if isinstance(f, dict)
                and f.get("coin") == coin and str(f.get("oid")) == str(order_id)]
    if not matching:
        return FillEvidence(False, reason="matching fill not found")
    total = 0.0
    for fill in matching:
        try:
            size = float(fill["sz"])
        except (KeyError, ValueError, TypeError, OverflowError):
            return FillEvidence(False, reason="invalid fill size")
        if not (0 < size < float("inf")):
            return FillEvidence(False, reason="invalid fill size")
        total += size
    if not (0 < total < float("inf")):
        return FillEvidence(False, reason="invalid aggregate fill size")
    return FillEvidence(True, filled_size=total, reason="matching exchange fills")
