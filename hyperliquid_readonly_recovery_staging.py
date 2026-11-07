"""Read-only order/fill/position recovery orchestration for offline staging.

Injected Info client only; no trading, secrets or DB writes. Missing evidence
or nonfinal order always keeps the entry fence.
"""
from entry_recovery_decision_staging import Decision, decide_recovery
from hyperliquid_order_status_staging import read_order_finality
from hyperliquid_fill_readonly_staging import read_order_fill_snapshot
from hyperliquid_position_readonly_staging import read_position_evidence

def reconcile_order_and_position(info, address, *, coin, order_id, requested_size):
    final = read_order_finality(info, address, coin=coin, order_id=order_id)
    if final is not True:
        return Decision.KEEP_FENCED
    fills = read_order_fill_snapshot(
        info, address, coin=coin, order_id=order_id,
        requested_size=requested_size, order_final=final)
    position = read_position_evidence(info, address, coin=coin)
    return decide_recovery(order_final=final, fill_snapshot=fills, position=position)
