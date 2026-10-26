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
    if fill_snapshot.has_exposure or size > 0:
        return Decision.OWN_POSITION
    return Decision.RELEASE_NO_FILL
