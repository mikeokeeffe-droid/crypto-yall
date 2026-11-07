"""Conservative read-only Hyperliquid order finality check (staging only).

Requires explicit authoritative status and never infers finality from fills.
Unknown or unsupported statuses fail closed.
"""
FINAL_STATUSES = frozenset(("filled", "canceled", "cancelled", "rejected", "expired"))


def read_order_status(info, address, *, coin, order_id):
    try:
        response = info.order_status(address, order_id)
    except Exception:
        return None
    if not isinstance(response, dict):
        return None
    status_obj = response.get("order")
    if not isinstance(status_obj, dict):
        return None
    order = status_obj.get("order")
    if not isinstance(order, dict):
        return None
    if order.get("coin") != coin or str(order.get("oid")) != str(order_id):
        return None
    status = status_obj.get("status")
    if not isinstance(status, str):
        return None
    status = status.lower()
    return status


def read_order_finality(info, address, *, coin, order_id):
    status = read_order_status(info, address, coin=coin, order_id=order_id)
    if status in FINAL_STATUSES:
        return True
    if status in ("open", "triggered"):
        return False
    return None
