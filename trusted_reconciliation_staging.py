"""Offline reconciliation decisions; no network calls and no order submission."""
from dataclasses import dataclass
from hyperliquid_fill_verification_staging import verify_order_fills
from hyperliquid_position_snapshot_staging import inspect_user_state_position

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

def verify_handoff(*, coin, order_id, fills, open_orders, user_state, fresh):
    fill = verify_order_fills(fills=fills, coin=coin, order_id=order_id,
                              snapshot_fresh=fresh, open_orders=open_orders)
    pos = inspect_user_state_position(user_state, coin, snapshot_fresh=fresh)
    if not fill.verified:
        return Decision(False, fill.reason)
    if not pos.valid or pos.flat:
        return Decision(False, "active position not confirmed")
    return Decision(True, "matching fill and active position confirmed")

def verify_release(*, coin, open_orders, user_state, fresh):
    pos = inspect_user_state_position(user_state, coin, snapshot_fresh=fresh)
    if not pos.valid or not pos.flat:
        return Decision(False, "position not verified flat")
    if not fresh or not isinstance(open_orders, list):
        return Decision(False, "open order snapshot unavailable")
    if any(not isinstance(o, dict) or not o.get("coin") for o in open_orders):
        return Decision(False, "ambiguous open order data")
    if any(o["coin"] == coin for o in open_orders):
        return Decision(False, "outstanding order on coin")
    return Decision(True, "flat and no outstanding orders")
