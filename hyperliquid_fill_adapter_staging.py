"""Offline adapter for Hyperliquid-style order fills; no network or credentials.

Input records must be obtained by a separate authenticated read-only exchange
adapter. Missing or ambiguous evidence fails closed (returns None).
"""
from math import isfinite
from partial_fill_accounting_staging import reconcile_fill_snapshot

def snapshot_from_hyperliquid_fills(*, coin, order_id, requested_size,
                                   fills, order_final):
    if not isinstance(coin, str) or not coin or order_id is None:
        return None
    if not isinstance(fills, list) or not isinstance(order_final, bool):
        return None
    matched = []
    for fill in fills:
        if not isinstance(fill, dict):
            return None
        if str(fill.get("oid")) != str(order_id):
            continue
        if fill.get("coin") != coin:
            return None  # Same order ID with inconsistent coin: fail closed
        try:
            size = float(fill["sz"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not isfinite(size) or size <= 0:
            return None
        matched.append(size)
    return reconcile_fill_snapshot(
        requested_size=requested_size, fill_sizes=matched, order_final=order_final)
