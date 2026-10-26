"""Offline partial-fill accounting model: fail closed on missing or ambiguous data.

This is a pure staging helper. Real exchange fill parsing, order status and
durable ownership handoff must be integrated and reviewed separately.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class FillSnapshot:
    requested_size: float
    filled_size: float
    remaining_size: float
    complete: bool
    has_exposure: bool

def reconcile_fill_snapshot(*, requested_size, fill_sizes, order_final):
    """Return exposure snapshot, or None when fill evidence is invalid.

    Never interpret a partial fill as an unfilled rejection. Callers must
    retain the entry fence until position ownership is durably reconciled.
    """
    try:
        requested = float(requested_size)
        sizes = [float(x) for x in fill_sizes]
    except (ValueError, TypeError, OverflowError):
        return None
    if not isfinite(requested) or requested <= 0:
        return None
    if any(not isfinite(x) or x <= 0 for x in sizes):
        return None
    filled = sum(sizes)
    if not isfinite(filled) or filled > requested + 1e-9:
        return None
    remaining = max(0.0, requested - filled)
    return FillSnapshot(
        requested_size=requested,
        filled_size=filled,
        remaining_size=remaining,
        complete=bool(order_final) and remaining <= 1e-9,
        has_exposure=filled > 0,
    )
