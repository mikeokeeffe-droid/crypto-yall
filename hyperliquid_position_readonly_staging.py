"""Offline-safe read-only Hyperliquid position evidence adapter.

Uses injected Info client. No orders, signing, or secrets. A missing coin in a
valid user_state is flat; malformed/ambiguous responses fail closed.
"""
from math import isfinite
from entry_recovery_decision_staging import PositionEvidence

def read_position_evidence(info, address, *, coin):
    if not isinstance(coin, str) or not coin:
        return None
    try:
        state = info.user_state(address)
    except Exception:
        return None
    if not isinstance(state, dict):
        return None
    positions = state.get("assetPositions")
    if not isinstance(positions, list):
        return None
    matches = []
    for item in positions:
        if not isinstance(item, dict):
            return None
        position = item.get("position")
        if not isinstance(position, dict):
            return None
        if position.get("coin") != coin:
            continue
        try:
            size = float(position["szi"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not isfinite(size):
            return None
        matches.append(abs(size))
    if len(matches) > 1:
        return None
    return PositionEvidence(confirmed=True, size=matches[0] if matches else 0.0)
