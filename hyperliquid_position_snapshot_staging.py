"""Pure read-only validation of Hyperliquid user_state position snapshots.

No API requests are made here. Caller supplies an independently fetched,
fresh user_state object. Missing/malformed snapshots fail closed.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PositionEvidence:
    valid: bool
    flat: bool = False
    signed_size: float = 0.0


def inspect_user_state_position(user_state: dict | None, coin: str,
                                *, snapshot_fresh: bool) -> PositionEvidence:
    if not snapshot_fresh or not coin or not isinstance(user_state, dict):
        return PositionEvidence(False)
    positions = user_state.get("assetPositions")
    if not isinstance(positions, list):
        return PositionEvidence(False)
    sizes = []
    for item in positions:
        if not isinstance(item, dict) or not isinstance(item.get("position"), dict):
            return PositionEvidence(False)
        pos = item["position"]
        if pos.get("coin") != coin:
            continue
        try:
            size = float(pos["szi"])
        except (KeyError, ValueError, TypeError, OverflowError):
            return PositionEvidence(False)
        if not isfinite(size):
            return PositionEvidence(False)
        sizes.append(size)
    if len(sizes) > 1:
        return PositionEvidence(False)
    signed_size = sizes[0] if sizes else 0.0
    return PositionEvidence(True, flat=signed_size == 0, signed_size=signed_size)
