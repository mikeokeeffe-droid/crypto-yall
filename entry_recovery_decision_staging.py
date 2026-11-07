"""Offline order/position reconciliation decision, never submits orders.

Conservative: any uncertainty, open order or exposure retains the entry fence.
Only a final order, zero fills and confirmed flat position permits release.
"""
from dataclasses import dataclass
from enum import Enum

class Decision(Enum):
    KEEP_FENCED = "keep_fenced"
    OWN_POSITION = "own_position"
    RELEASE_NO_FILL = "release_no_fill"

@dataclass(frozen=True)
class PositionEvidence:
    confirmed: bool
    size: float

def decide_recovery(*, order_final, fill_snapshot, position):
    if order_final is not True:
        return Decision.KEEP_FENCED
    if fill_snapshot is None or position is None or not position.confirmed:
        return Decision.KEEP_FENCED
    try:
        from math import isfinite
        size = float(position.size)
        if not isfinite(size) or size < 0:
            return Decision.KEEP_FENCED
    except (TypeError, ValueError, OverflowError):
        return Decision.KEEP_FENCED
    # A release requires internally consistent, explicitly zero-fill evidence.
    # Do not trust a false exposure flag if the reported fill size disagrees.
    try:
        filled = float(fill_snapshot.filled_size)
        requested = float(fill_snapshot.requested_size)
        remaining = float(fill_snapshot.remaining_size)
        if (not all(isfinite(x) for x in (filled, requested, remaining))
                or requested <= 0 or filled < 0 or remaining < 0
                or filled > requested or abs((requested - filled) - remaining) > 1e-9):
            return Decision.KEEP_FENCED
    except (AttributeError, TypeError, ValueError, OverflowError):
        return Decision.KEEP_FENCED
    if filled > 0 or fill_snapshot.has_exposure or size > 0:
        return Decision.OWN_POSITION
    return Decision.RELEASE_NO_FILL
