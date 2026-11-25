"""Read-only staging fill snapshot from injected Hyperliquid Info client.

Never submits orders. The caller must separately prove order_final using
authoritative order status; fills alone cannot establish finality.
"""
from hyperliquid_fill_adapter_staging import snapshot_from_hyperliquid_fills

def read_order_fill_snapshot(info, address, *, coin, order_id, requested_size,
                             order_final):
    if not isinstance(order_final, bool):
        return None
    try:
        fills = info.user_fills(address)
    except Exception:
        return None
    return snapshot_from_hyperliquid_fills(
        coin=coin, order_id=order_id, requested_size=requested_size,
        fills=fills, order_final=order_final)
